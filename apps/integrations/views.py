from rest_framework import serializers
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .services import SkudSyncService, SkudAttendancePushService


class OrgIdSerializer(serializers.Serializer):
    organization_id = serializers.IntegerField(min_value=1)


class SyncPhotosSerializer(serializers.Serializer):
    organization_id = serializers.IntegerField(min_value=1)
    limit = serializers.IntegerField(min_value=1, max_value=200, default=20)
    offset = serializers.IntegerField(min_value=0, default=0)


class PushAttendanceSerializer(serializers.Serializer):
    event_id = serializers.IntegerField(min_value=1)


class SyncOrganizationsAPIView(APIView):
    def post(self, request):
        try:
            service = SkudSyncService()
            result = service.sync_organizations()
            return Response(result, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class FullSyncAPIView(APIView):
    def post(self, request):
        ser = OrgIdSerializer(data=request.data)
        if not ser.is_valid():
            return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)

        download_photos = bool(request.data.get("download_photos", False))
        target_date = request.data.get("date")

        try:
            service = SkudSyncService()
            result = service.full_sync(
                organization_id=ser.validated_data["organization_id"],
                download_photos=download_photos,
                target_date=target_date,
            )
            return Response(result, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class SyncPhotosAPIView(APIView):
    def post(self, request):
        ser = SyncPhotosSerializer(data=request.data)
        if not ser.is_valid():
            return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            service = SkudSyncService()
            result = service.sync_photos(**ser.validated_data)
            return Response(result, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class PushAttendanceAPIView(APIView):
    """
    Bitta RecognitionEvent ni SKUD global tizimiga qo'lda yuboradi.
    Asosan test va qayta yuborish uchun ishlatiladi.
    POST body: { "event_id": 123 }
    """

    def post(self, request):
        ser = PushAttendanceSerializer(data=request.data)
        if not ser.is_valid():
            return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            service = SkudAttendancePushService()
            result = service.push_by_event_id(ser.validated_data["event_id"])
            return Response(result, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SyncAuditoriumCamerasAPIView(APIView):
    """
    ExternalClassroom → Auditorium → AuditoriumCamera bog'liqligini yaratadi.
    POST body: { "organization_id": 1 }
    """

    def post(self, request):
        ser = OrgIdSerializer(data=request.data)
        if not ser.is_valid():
            return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            service = SkudSyncService()
            result = service.sync_auditorium_cameras(ser.validated_data["organization_id"])
            return Response(result, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)