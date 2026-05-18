"""
RecognitionEventService.recognize_track_and_record_by_embedding uchun testlar.

Har bir test nimani tekshiradi:
  - rejected  → DB ga yozuv saqlanmaydi, track cooldown o'rnatiladi
  - review    → bitta yozuv (upsert): yaxshiroq sim bo'lsa yangilanadi
  - accepted  → yozuv saqlanadi, review yozuvlar o'chiriladi, lock yaratiladi
  - lock      → band talaba uchun ikkinchi accepted o'tkazib yuboriladi
"""

import numpy as np
from unittest.mock import MagicMock, patch

from django.core.files.base import ContentFile
from django.test import TestCase
from django.utils import timezone

from apps.attendance.models import AttendanceLock, RecognitionEvent, TrackSession
from apps.attendance.services import FaceTrackService, RecognitionEventService
from apps.integrations.models import ExternalClass, ExternalOrganization, ExternalStudent


# ─── Yordamchi funksiyalar ───────────────────────────────────────────────────

def _make_embedding():
    v = np.random.randn(512).astype(np.float32)
    return v / np.linalg.norm(v)


# ─── Base test sinfi ─────────────────────────────────────────────────────────

class RecognitionServiceBase(TestCase):
    """
    Har bir testda:
      - Haqiqiy PostgreSQL test DB'ga yoziladi
      - ExternalOrganization + ExternalStudent fixture yaratiladi
      - InsightFace, fayl tizimi, SKUD push va track cooldown mock qilinadi

    Eslatma: should_skip_recognition global mock qilinadi, chunki unit
    testlar 0ms oralig'ida ishlaydi va 30s cooldown barcha keyingi
    chaqiriqlarni bloklaydi. Cooldown xulq-atvori alohida TrackCooldownTests da
    tekshiriladi.
    """

    def setUp(self):
        # ── DB fixtures ──────────────────────────────────────────────────────
        self.org = ExternalOrganization.objects.create(
            organization_id=10,
            organization_name="71-maktab",
        )
        self.ext_class = ExternalClass.objects.create(
            class_id=100,
            class_name="11-A",
            organization=self.org,
        )
        self.student = ExternalStudent.objects.create(
            pinfl="99999999999",
            full_name="Ali Valiyev",
            organization=self.org,
            class_obj=self.ext_class,
        )

        # ── Service ──────────────────────────────────────────────────────────
        self.svc = RecognitionEventService()
        self.embedding = _make_embedding()

        # ── Mock: fayl tizimi ────────────────────────────────────────────────
        self.svc._to_base64 = MagicMock(return_value="data:image/jpeg;base64,FAKE")
        self.svc._to_file = MagicMock(
            return_value=ContentFile(b"fake", name="face.jpg")
        )
        self.svc._push_to_skud = MagicMock(return_value={"status": "ok"})

        # ImageField.save real fayl tizimiga murojaat qilmasligi uchun
        p_img = patch("django.db.models.fields.files.FieldFile.save")
        p_img.start()
        self.addCleanup(p_img.stop)

        # LessonEmbeddingCache yo'q — dars vaqtidan tashqarida test
        p_cache = patch(
            "apps.attendance.services._get_lesson_embedding_cache",
            return_value=(None, None),
        )
        p_cache.start()
        self.addCleanup(p_cache.stop)

        # Track cooldown bypass: 30s ni kutmaslik uchun
        # (unit testlar millisoniyalarda ishlaydi)
        p_skip = patch.object(
            FaceTrackService,
            "should_skip_recognition",
            return_value=(False, None),
        )
        p_skip.start()
        self.addCleanup(p_skip.stop)

    # ── Yordamchi: servisni bir marta chaqiradi ──────────────────────────────

    def _call(self, decision, score, track_key="cam1_track_test"):
        result = {
            "decision": decision,
            "best_match": {
                "student_id": self.student.id,
                "pinfl": self.student.pinfl,
                "full_name": self.student.full_name,
                "best_score": score,
                "organization_id": self.org.organization_id,
            },
            "top_candidates": [],
        }
        with patch.object(
            self.svc.search_service,
            "decide_match_by_embedding",
            return_value=result,
        ):
            return self.svc.recognize_track_and_record_by_embedding(
                track_key=track_key,
                image_path="/tmp/fake_face.jpg",
                query_embedding=self.embedding,
                organization_id=self.org.organization_id,
                camera_id=None,
                accept_threshold=0.70,
                review_threshold=0.55,
            )

    def _call_no_match(self):
        result = {"decision": "rejected", "best_match": None, "top_candidates": []}
        with patch.object(
            self.svc.search_service, "decide_match_by_embedding", return_value=result
        ):
            return self.svc.recognize_track_and_record_by_embedding(
                track_key="cam1_track_nomatch",
                image_path="/tmp/fake.jpg",
                query_embedding=self.embedding,
                organization_id=self.org.organization_id,
                camera_id=None,
            )


# ─── 1. REJECTED testlari ────────────────────────────────────────────────────

class RejectedTests(RecognitionServiceBase):

    def test_no_match_does_not_save_event(self):
        """best=None bo'lsa RecognitionEvent saqlanmaydi."""
        out = self._call_no_match()
        self.assertEqual(out["status"], "rejected")
        self.assertEqual(RecognitionEvent.objects.count(), 0)

    def test_below_threshold_does_not_save_event(self):
        """similarity < review_threshold → DB ga yozuv saqlanmaydi."""
        out = self._call("rejected", score=0.40)
        self.assertEqual(out["status"], "rejected")
        self.assertEqual(RecognitionEvent.objects.count(), 0)

    def test_many_rejected_no_events(self):
        """10 ta rejected urinish → DB bo'sh."""
        for s in [0.10, 0.20, 0.30, 0.40, 0.45, 0.35, 0.50, 0.48, 0.42, 0.44]:
            self._call("rejected", score=s)
        self.assertEqual(RecognitionEvent.objects.count(), 0)


# ─── 2. REVIEW testlari ──────────────────────────────────────────────────────

class ReviewTests(RecognitionServiceBase):

    def test_first_review_creates_one_event(self):
        """Birinchi review urinishida bitta RecognitionEvent yaratiladi."""
        out = self._call("review", score=0.62)
        self.assertEqual(out["status"], "review_recorded")
        self.assertEqual(RecognitionEvent.objects.count(), 1)
        ev = RecognitionEvent.objects.first()
        self.assertEqual(ev.decision, RecognitionEvent.DECISION_REVIEW)
        self.assertAlmostEqual(ev.similarity, 0.62, places=3)

    def test_second_review_worse_score_no_new_event(self):
        """Ikkinchi urinish past similarity → yangi yozuv yaratilmaydi."""
        self._call("review", score=0.65)
        out = self._call("review", score=0.58)

        self.assertEqual(out["status"], "review_exists")
        self.assertEqual(RecognitionEvent.objects.count(), 1)
        ev = RecognitionEvent.objects.first()
        self.assertAlmostEqual(ev.similarity, 0.65, places=3)

    def test_second_review_better_score_updates_existing(self):
        """Ikkinchi urinish yuqori similarity → mavjud yozuv yangilanadi."""
        self._call("review", score=0.58)
        out = self._call("review", score=0.66)

        self.assertEqual(out["status"], "review_updated")
        self.assertEqual(RecognitionEvent.objects.count(), 1)
        ev = RecognitionEvent.objects.first()
        self.assertAlmostEqual(ev.similarity, 0.66, places=3)

    def test_many_reviews_stay_one_record_with_best_score(self):
        """10 ta review urinishi → 1 ta yozuv, eng yuqori similarity saqlangan."""
        scores = [0.56, 0.60, 0.58, 0.64, 0.61, 0.63, 0.57, 0.67, 0.65, 0.62]
        for s in scores:
            self._call("review", score=s)

        self.assertEqual(RecognitionEvent.objects.count(), 1)
        ev = RecognitionEvent.objects.first()
        self.assertAlmostEqual(ev.similarity, max(scores), places=3)

    def test_review_event_id_returned(self):
        """Natijada event_id mavjud bo'lishi kerak."""
        out = self._call("review", score=0.62)
        self.assertIn("event_id", out)
        self.assertIsNotNone(out["event_id"])


# ─── 3. ACCEPTED testlari ────────────────────────────────────────────────────

class AcceptedTests(RecognitionServiceBase):

    def test_accepted_saves_event(self):
        """Accepted qaror RecognitionEvent saqlanadi."""
        out = self._call("accepted", score=0.82)
        self.assertEqual(out["status"], "recorded_and_locked")
        self.assertEqual(RecognitionEvent.objects.filter(decision="accepted").count(), 1)

    def test_accepted_creates_lock(self):
        """Accepted bo'lgandan so'ng AttendanceLock yaratiladi."""
        self._call("accepted", score=0.82)
        lock = AttendanceLock.objects.filter(student_id=self.student.id).first()
        self.assertIsNotNone(lock)
        self.assertTrue(lock.is_active)

    def test_accepted_deletes_pending_reviews(self):
        """Accepted bo'lganda bugungi review yozuvlar o'chiriladi."""
        self._call("review", score=0.62)
        self.assertEqual(RecognitionEvent.objects.filter(decision="review").count(), 1)

        self._call("accepted", score=0.82)

        self.assertEqual(
            RecognitionEvent.objects.filter(decision="review").count(), 0,
            "Review yozuvlar accepted dan keyin o'chirilishi kerak",
        )
        self.assertEqual(RecognitionEvent.objects.filter(decision="accepted").count(), 1)

    def test_accepted_when_locked_skips(self):
        """Talaba locked bo'lsa ikkinchi accepted o'tkazib yuboriladi."""
        # should_skip_recognition mocked = (False, None), shuning uchun
        # ikkinchi urinish global lock checkigacha yetib boradi
        self._call("accepted", score=0.82)
        out = self._call("accepted", score=0.85)

        self.assertEqual(out["status"], "skipped_locked_after_search")
        self.assertEqual(RecognitionEvent.objects.filter(decision="accepted").count(), 1)

    def test_accepted_skud_push_called(self):
        """Accepted bo'lganda SKUD push chaqiriladi."""
        self._call("accepted", score=0.82)
        self.svc._push_to_skud.assert_called_once()

    def test_accepted_result_has_required_fields(self):
        """Natijada event_id, lock_id, decision maydonlari bor."""
        out = self._call("accepted", score=0.82)
        for field in ("event_id", "lock_id", "track_id", "decision", "best_match"):
            self.assertIn(field, out)


# ─── 4. TRACK SESSION testlari ───────────────────────────────────────────────

class TrackSessionTests(RecognitionServiceBase):

    def test_new_track_created_on_first_call(self):
        """Birinchi chaqiriqda yangi TrackSession yaratiladi."""
        self._call("rejected", score=0.40, track_key="cam_track_001")
        self.assertEqual(TrackSession.objects.filter(track_key="cam_track_001").count(), 1)

    def test_same_track_reused(self):
        """Bir xil track_key → bitta TrackSession (yangi yaratilmaydi)."""
        self._call("rejected", score=0.40, track_key="cam_track_002")
        self._call("rejected", score=0.42, track_key="cam_track_002")
        self.assertEqual(TrackSession.objects.filter(track_key="cam_track_002").count(), 1)

    def test_different_track_keys_create_separate_sessions(self):
        """Har xil track_key → alohida TrackSession."""
        self._call("rejected", score=0.40, track_key="cam_track_003")
        self._call("rejected", score=0.40, track_key="cam_track_004")
        self.assertEqual(TrackSession.objects.count(), 2)

    def test_accepted_marks_track_recognized(self):
        """Accepted bo'lgandan so'ng track.status RECOGNIZED va student_id o'rnatiladi."""
        self._call("accepted", score=0.82, track_key="cam_track_005")
        track = TrackSession.objects.get(track_key="cam_track_005")
        self.assertEqual(track.status, TrackSession.STATUS_RECOGNIZED)
        self.assertEqual(track.student_id, self.student.id)
        self.assertIsNotNone(track.recognized_at)

    def test_rejected_updates_best_score(self):
        """Track.best_score har doim eng yuqori qiymatni saqlaydi."""
        tk = "cam_track_006"
        self._call("rejected", score=0.40, track_key=tk)
        self._call("rejected", score=0.50, track_key=tk)
        self._call("rejected", score=0.45, track_key=tk)

        track = TrackSession.objects.get(track_key=tk)
        self.assertAlmostEqual(track.best_score, 0.50, places=3)

    def test_rejected_increments_recognition_count(self):
        """Har rejected urinishda track.recognition_count oshadi."""
        tk = "cam_track_007"
        self._call("rejected", score=0.40, track_key=tk)
        self._call("rejected", score=0.42, track_key=tk)

        track = TrackSession.objects.get(track_key=tk)
        self.assertEqual(track.recognition_count, 2)


# ─── 5. INTEGRATSION: rejected → review → accepted to'liq oqim ──────────────

class FullFlowTests(RecognitionServiceBase):

    def test_rejected_then_review_then_accepted(self):
        """
        Haqiqiy stsenariy: Ali 3 marta ko'rinadi.
          1-chi: 40% → rejected  — DB bo'sh
          2-chi: 62% → review    — 1 ta yozuv
          3-chi: 78% → accepted  — review o'chadi, 1 ta accepted
        """
        out1 = self._call("rejected", score=0.40)
        self.assertEqual(out1["status"], "rejected")
        self.assertEqual(RecognitionEvent.objects.count(), 0)

        out2 = self._call("review", score=0.62)
        self.assertEqual(out2["status"], "review_recorded")
        self.assertEqual(RecognitionEvent.objects.filter(decision="review").count(), 1)
        self.assertEqual(RecognitionEvent.objects.filter(decision="accepted").count(), 0)

        out3 = self._call("accepted", score=0.78)
        self.assertEqual(out3["status"], "recorded_and_locked")
        self.assertEqual(RecognitionEvent.objects.filter(decision="review").count(), 0)
        self.assertEqual(RecognitionEvent.objects.filter(decision="accepted").count(), 1)
        self.assertEqual(RecognitionEvent.objects.count(), 1, "Jami faqat 1 ta yozuv bo'lishi kerak")

    def test_many_reviews_then_accepted(self):
        """
        5 ta review → bitta yozuv (eng yaxshi 0.65).
        Keyin accepted → review o'chadi, faqat accepted qoladi.
        """
        for s in [0.57, 0.60, 0.63, 0.59, 0.65]:
            self._call("review", score=s)

        self.assertEqual(RecognitionEvent.objects.count(), 1)
        self.assertAlmostEqual(RecognitionEvent.objects.first().similarity, 0.65, places=3)

        self._call("accepted", score=0.80)

        self.assertEqual(RecognitionEvent.objects.count(), 1)
        ev = RecognitionEvent.objects.first()
        self.assertEqual(ev.decision, "accepted")
        self.assertAlmostEqual(ev.similarity, 0.80, places=3)

    def test_total_db_records_after_full_flow(self):
        """
        10 ta rejected + 5 ta review + 1 ta accepted = bazada faqat 1 ta yozuv.
        """
        for s in [0.30, 0.35, 0.40, 0.38, 0.42, 0.45, 0.41, 0.43, 0.39, 0.44]:
            self._call("rejected", score=s)
        for s in [0.57, 0.61, 0.64, 0.60, 0.65]:
            self._call("review", score=s)
        self._call("accepted", score=0.82)

        self.assertEqual(
            RecognitionEvent.objects.count(), 1,
            "16 ta urinishdan faqat 1 ta yozuv bo'lishi kerak",
        )
        self.assertEqual(RecognitionEvent.objects.first().decision, "accepted")

    def test_only_rejected_no_events_ever(self):
        """Faqat rejected bo'lsa DB doim bo'sh qoladi."""
        for s in [0.10, 0.20, 0.30, 0.40, 0.50, 0.54]:
            self._call("rejected", score=s)
        self.assertEqual(RecognitionEvent.objects.count(), 0)
