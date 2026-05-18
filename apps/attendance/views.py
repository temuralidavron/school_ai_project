import datetime

from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.attendance.models import RecognitionEvent


class RecognitionEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = RecognitionEvent
        fields = (
            "id", "full_name", "pinfl", "decision", "similarity",
            "recognized_at", "camera_id", "organization_id",
            "source", "model_name", "image", "meta_json",
        )


class ReviewListView(APIView):
    """
    GET /api/attendance/review/?date=2026-04-30&org=<org_id>
    Bugungi decision=review hodisalar ro'yxati.
    """

    def get(self, request):
        date_str = request.query_params.get("date")
        org_id = request.query_params.get("org")

        if date_str:
            try:
                day = datetime.date.fromisoformat(date_str)
            except ValueError:
                return Response({"error": "date format: YYYY-MM-DD"}, status=400)
        else:
            day = timezone.now().date()

        try:
            limit = min(int(request.query_params.get("limit", 50)), 500)
            offset = max(int(request.query_params.get("offset", 0)), 0)
        except (ValueError, TypeError):
            return Response({"error": "limit va offset butun son bo'lishi kerak"}, status=400)

        qs = RecognitionEvent.objects.filter(
            decision=RecognitionEvent.DECISION_REVIEW,
            recognized_at__date=day,
        ).select_related("student", "camera").order_by("-recognized_at")

        if org_id:
            qs = qs.filter(organization_id=org_id)

        total = qs.count()
        serializer = RecognitionEventSerializer(qs[offset:offset + limit], many=True, context={"request": request})
        return Response({
            "date": str(day),
            "count": total,
            "limit": limit,
            "offset": offset,
            "results": serializer.data,
        })


class ReviewConfirmView(APIView):
    """
    POST /api/attendance/review/<id>/confirm/
    decision=review hodisani accepted ga o'tkazib SKUD ga yuboradi.
    """

    def post(self, request, pk):
        try:
            event = RecognitionEvent.objects.select_related("student").get(pk=pk)
        except RecognitionEvent.DoesNotExist:
            return Response({"error": "topilmadi"}, status=404)

        if event.decision != RecognitionEvent.DECISION_REVIEW:
            return Response(
                {"error": f"decision={event.decision}, faqat review hodisalar tasdiqlanadi"},
                status=400,
            )

        if not event.student:
            return Response({"error": "student bog'lanmagan"}, status=400)

        from apps.attendance.services import AttendanceLockService
        from apps.integrations.services import SkudAttendancePushService

        event.decision = RecognitionEvent.DECISION_ACCEPTED
        event.save(update_fields=["decision", "updated_at"])

        lock_svc = AttendanceLockService()
        lock = lock_svc.create_lock(
            student_id=event.student_id,
            organization_id=event.organization_id,
            camera_id=event.camera_id,
            reason="manual_confirm",
        )

        push_svc = SkudAttendancePushService()
        push_result = push_svc.push_recognition_event(event)

        return Response({
            "status": "confirmed",
            "event_id": event.id,
            "lock_id": lock.id,
            "skud_push": push_result,
        })


class ReviewRejectView(APIView):
    """
    POST /api/attendance/review/<id>/reject/
    decision=review hodisani rejected ga o'tkazadi.
    """

    def post(self, request, pk):
        try:
            event = RecognitionEvent.objects.get(pk=pk)
        except RecognitionEvent.DoesNotExist:
            return Response({"error": "topilmadi"}, status=404)

        if event.decision != RecognitionEvent.DECISION_REVIEW:
            return Response(
                {"error": f"decision={event.decision}, faqat review hodisalar rad etiladi"},
                status=400,
            )

        event.decision = RecognitionEvent.DECISION_REJECTED
        event.save(update_fields=["decision", "updated_at"])

        return Response({"status": "rejected", "event_id": event.id})


class TodayAttendanceView(APIView):
    """
    GET /api/attendance/today/?org=<org_id>&date=2026-04-30
    Bugungi qabul qilingan davomat (decision=accepted) ro'yxati.
    """

    def get(self, request):
        date_str = request.query_params.get("date")
        org_id = request.query_params.get("org")

        if date_str:
            try:
                day = datetime.date.fromisoformat(date_str)
            except ValueError:
                return Response({"error": "date format: YYYY-MM-DD"}, status=400)
        else:
            day = timezone.now().date()

        try:
            limit = min(int(request.query_params.get("limit", 50)), 500)
            offset = max(int(request.query_params.get("offset", 0)), 0)
        except (ValueError, TypeError):
            return Response({"error": "limit va offset butun son bo'lishi kerak"}, status=400)

        qs = RecognitionEvent.objects.filter(
            decision=RecognitionEvent.DECISION_ACCEPTED,
            recognized_at__date=day,
        ).select_related("student", "camera").order_by("recognized_at")

        if org_id:
            qs = qs.filter(organization_id=org_id)

        total = qs.count()
        results = []
        for event in qs[offset:offset + limit]:
            results.append({
                "event_id": event.id,
                "full_name": event.full_name,
                "pinfl": event.pinfl,
                "camera": str(event.camera) if event.camera else None,
                "recognized_at": event.recognized_at,
                "similarity": round(event.similarity, 3) if event.similarity else None,
            })

        return Response({
            "date": str(day),
            "organization_id": org_id,
            "total_accepted": total,
            "limit": limit,
            "offset": offset,
            "results": results,
        })


class AttendanceStatsView(APIView):
    """
    GET /api/attendance/stats/?date=2026-04-30&org=<org_id>
    Qisqa statistika: accepted, review, rejected soni.
    """

    def get(self, request):
        date_str = request.query_params.get("date")
        org_id = request.query_params.get("org")

        if date_str:
            try:
                day = datetime.date.fromisoformat(date_str)
            except ValueError:
                return Response({"error": "date format: YYYY-MM-DD"}, status=400)
        else:
            day = timezone.now().date()

        qs = RecognitionEvent.objects.filter(recognized_at__date=day)
        if org_id:
            qs = qs.filter(organization_id=org_id)

        accepted = qs.filter(decision=RecognitionEvent.DECISION_ACCEPTED).count()
        review = qs.filter(decision=RecognitionEvent.DECISION_REVIEW).count()
        rejected = qs.filter(decision=RecognitionEvent.DECISION_REJECTED).count()

        return Response({
            "date": str(day),
            "organization_id": org_id,
            "accepted": accepted,
            "review": review,
            "rejected": rejected,
            "total": accepted + review + rejected,
        })
