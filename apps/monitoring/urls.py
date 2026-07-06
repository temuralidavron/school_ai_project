from django.urls import path
from .views import (
    dashboard,
    video_file_stream,
    pipeline_stats_api,
    room_attendance,
    mjpeg_stream,
    room_attendance_api,
    attendance_comparison,
    MonitoringStatsAPIView,
    MonitoringLiveAPIView,
    MonitoringHourlyAPIView,
    MonitoringReviewAPIView,
    MonitoringCamerasAPIView,
    MonitoringCameraAttendanceAPIView,
    MonitoringComparisonAPIView,
)

urlpatterns = [
    path("", dashboard, name="monitoring-dashboard"),
    path("video-file/", video_file_stream, name="monitoring-video-file"),
    path("api/pipeline-stats/", pipeline_stats_api, name="monitoring-pipeline-stats"),

    # Rasm qiyosi sahifasi
    path("comparison/", attendance_comparison, name="monitoring-comparison"),

    # Jonli kamera xonasi davomati
    path("room/<int:camera_id>/", room_attendance, name="monitoring-room"),
    path("room/<int:camera_id>/mjpeg/", mjpeg_stream, name="monitoring-mjpeg"),
    path("room/<int:camera_id>/api/", room_attendance_api, name="monitoring-room-api"),

    # API endpointlar
    path("api/stats/", MonitoringStatsAPIView.as_view(), name="monitoring-stats"),
    path("api/live/", MonitoringLiveAPIView.as_view(), name="monitoring-live"),
    path("api/hourly/", MonitoringHourlyAPIView.as_view(), name="monitoring-hourly"),
    path("api/review/", MonitoringReviewAPIView.as_view(), name="monitoring-review"),
    path("api/cameras/", MonitoringCamerasAPIView.as_view(), name="monitoring-cameras"),
    path("api/cameras/<int:camera_id>/attendance/",
         MonitoringCameraAttendanceAPIView.as_view(),
         name="monitoring-camera-attendance"),
    path("api/comparison/",
         MonitoringComparisonAPIView.as_view(),
         name="monitoring-comparison-api"),
]
