from rest_framework import serializers
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from apps.cameras.models import Camera, CameraROI


class CameraROISerializer(serializers.Serializer):
    camera_id = serializers.IntegerField(min_value=1)
    roi_x = serializers.IntegerField(min_value=0)
    roi_y = serializers.IntegerField(min_value=0)
    roi_width = serializers.IntegerField(min_value=1)
    roi_height = serializers.IntegerField(min_value=1)
    frame_width = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    frame_height = serializers.IntegerField(min_value=1, required=False, allow_null=True)


class SetCameraROIAPIView(APIView):
    """
    Kamera uchun ROI (Region of Interest) belgilaydi.
    ROI — framening qaysi qismini tanishda ishlatish.
    POST body: {
        "camera_id": 1,
        "roi_x": 400, "roi_y": 200,
        "roi_width": 600, "roi_height": 400,
        "frame_width": 1280,   # optional: scale up target
        "frame_height": 720
    }
    """

    def post(self, request):
        serializer = CameraROISerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        camera = Camera.objects.filter(id=data["camera_id"]).first()
        if not camera:
            return Response({"detail": f"Camera id={data['camera_id']} topilmadi"}, status=status.HTTP_404_NOT_FOUND)

        roi, created = CameraROI.objects.update_or_create(
            camera=camera,
            defaults={
                "roi_x": data["roi_x"],
                "roi_y": data["roi_y"],
                "roi_width": data["roi_width"],
                "roi_height": data["roi_height"],
                "frame_width": data.get("frame_width"),
                "frame_height": data.get("frame_height"),
            },
        )

        return Response({
            "camera_id": camera.id,
            "camera_name": camera.name,
            "roi": {
                "x": roi.roi_x, "y": roi.roi_y,
                "width": roi.roi_width, "height": roi.roi_height,
                "frame_width": roi.frame_width,
                "frame_height": roi.frame_height,
            },
            "created": created,
        })

    def delete(self, request):
        camera_id = request.data.get("camera_id")
        if not camera_id:
            return Response({"detail": "camera_id majburiy"}, status=status.HTTP_400_BAD_REQUEST)
        deleted, _ = CameraROI.objects.filter(camera_id=camera_id).delete()
        return Response({"deleted": deleted})


class CameraROIListAPIView(APIView):
    """Barcha kameralar ROI sozlamalarini ko'rsatadi."""

    def get(self, request):
        rois = CameraROI.objects.select_related("camera").all()
        data = []
        for roi in rois:
            data.append({
                "camera_id": roi.camera_id,
                "camera_name": roi.camera.name,
                "stream_url": roi.camera.stream_url,
                "roi_x": roi.roi_x, "roi_y": roi.roi_y,
                "roi_width": roi.roi_width, "roi_height": roi.roi_height,
                "frame_width": roi.frame_width, "frame_height": roi.frame_height,
            })
        return Response({"count": len(data), "results": data})
