"""
Davriy tozalash — eskirgan lock/track va frontal store.

Cron orqali chaqiriladi. Bularsiz DB/RAM uzoq ishlashda shishadi
(to'g'rilik buzilmaydi — lock vaqt filtri eskisini chetlaydi —
lekin jadvallar/RAM o'sib boradi).

Ishlatish:
    python manage.py maintenance
"""
from django.core.management.base import BaseCommand

from apps.attendance.services import (
    AttendanceLockService,
    FaceTrackService,
    _cleanup_frontal_store,
)


class Command(BaseCommand):
    help = "Eskirgan lock/track/frontal store ni tozalaydi (cron uchun)"

    def handle(self, *args, **options):
        locks = AttendanceLockService().deactivate_expired_locks()
        tracks = FaceTrackService().deactivate_stale_tracks()
        frontal = _cleanup_frontal_store()
        self.stdout.write(self.style.SUCCESS(
            f"Tozalandi: lock={locks}  track={tracks}  frontal_store={frontal}"
        ))
