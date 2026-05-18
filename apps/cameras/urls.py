from django.urls import path
from .views import SetCameraROIAPIView, CameraROIListAPIView

urlpatterns = [
    path("roi/", SetCameraROIAPIView.as_view(), name="camera-roi"),
    path("roi/list/", CameraROIListAPIView.as_view(), name="camera-roi-list"),
]
