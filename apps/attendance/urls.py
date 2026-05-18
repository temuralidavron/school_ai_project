from django.urls import path
from apps.attendance.views import (
    ReviewListView, ReviewConfirmView, ReviewRejectView,
    TodayAttendanceView, AttendanceStatsView,
)

urlpatterns = [
    path("review/", ReviewListView.as_view(), name="review-list"),
    path("review/<int:pk>/confirm/", ReviewConfirmView.as_view(), name="review-confirm"),
    path("review/<int:pk>/reject/", ReviewRejectView.as_view(), name="review-reject"),
    path("today/", TodayAttendanceView.as_view(), name="today-attendance"),
    path("stats/", AttendanceStatsView.as_view(), name="attendance-stats"),
]
