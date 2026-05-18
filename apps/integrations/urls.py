from django.urls import path
from .views import (
    SyncOrganizationsAPIView,
    FullSyncAPIView,
    SyncPhotosAPIView,
    PushAttendanceAPIView,
    SyncAuditoriumCamerasAPIView,
)

urlpatterns = [
    path("sync-organizations/", SyncOrganizationsAPIView.as_view(), name="sync-organizations"),
    path("full-sync/", FullSyncAPIView.as_view(), name="full-sync"),
    path("sync-photos/", SyncPhotosAPIView.as_view(), name="sync-photos"),
    path("push-attendance/", PushAttendanceAPIView.as_view(), name="push-attendance"),
    path("sync-auditorium-cameras/", SyncAuditoriumCamerasAPIView.as_view(), name="sync-auditorium-cameras"),
]