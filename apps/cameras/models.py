from django.db import models
from apps.common.models import BaseModel
from apps.common.fields import EncryptedTextField


class Building(BaseModel):
    hemis_id = models.BigIntegerField(null=True, blank=True)
    name = models.CharField(max_length=255, null=True, blank=True)
    is_active = models.BooleanField(null=True, blank=True)
    camera_count = models.IntegerField(null=True, blank=True)
    active_camera_count = models.IntegerField(null=True, blank=True)
    person_count = models.IntegerField(null=True, blank=True)
    active_person_count = models.IntegerField(null=True, blank=True)
    max_floor_count = models.IntegerField(null=True, blank=True)
    min_floor_count = models.IntegerField(null=True, blank=True)
    university = models.ForeignKey(
        "academics.University",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="buildings",
    )

    class Meta:
        db_table = "building"


class Auditorium(BaseModel):
    hemis_id = models.BigIntegerField(null=True, blank=True)
    code = models.CharField(max_length=255, null=True, blank=True)
    name = models.CharField(max_length=255, null=True, blank=True)
    volume = models.IntegerField(null=True, blank=True)
    floor = models.IntegerField(null=True, blank=True)
    is_active = models.BooleanField(null=True, blank=True)
    camera_count = models.IntegerField(null=True, blank=True)
    active_camera_count = models.IntegerField(null=True, blank=True)
    person_count = models.IntegerField(null=True, blank=True)
    active_person_count = models.IntegerField(null=True, blank=True)
    hemis_status = models.CharField(max_length=16)
    building = models.ForeignKey(Building, on_delete=models.SET_NULL, null=True, blank=True, related_name="auditoriums")
    auditorium_type = models.ForeignKey(
        "academics.Reference",
        on_delete=models.SET_NULL,
        db_column="auditoriumType_id",
        null=True,
        blank=True,
        related_name="auditorium_types",
    )

    class Meta:
        db_table = "auditorium"


class Camera(BaseModel):
    name = models.TextField()
    ip_address = models.TextField()
    username = EncryptedTextField()
    password = EncryptedTextField()
    rtsp_url_format = models.CharField(max_length=16, null=True, blank=True)
    camera_number = models.TextField(null=True, blank=True)
    stream_quality = models.IntegerField(null=True, blank=True)
    owner_id = models.IntegerField(null=True, blank=True)
    port = models.IntegerField(null=True, blank=True)
    path = models.TextField(null=True, blank=True)
    channel = models.IntegerField(null=True, blank=True)
    is_main_stream = models.BooleanField(null=True, blank=True)
    skud_device_id = models.CharField(max_length=64, unique=True, null=True, blank=True)
    stream_url = models.CharField(max_length=512, null=True, blank=True)
    organization_id = models.BigIntegerField(null=True, blank=True)
    is_active_stream = models.BooleanField(default=False)

    # PTZ boshqaruv
    onvif_port = models.IntegerField(default=80)
    ptz_preset_token = models.CharField(max_length=64, null=True, blank=True,
                                        help_text="ONVIF home preset token (dars yo'q paytda shu pozitsiya)")

    # ─── Patrul (aylanish) rejimi ──────────────────────────────────────────────
    PATROL_DEFAULT = "default"   # global settings.PATROL_MODE ishlatiladi
    PATROL_OFF     = "off"       # aylanmaydi (statik)
    PATROL_PRESET  = "preset"    # CameraPatrolPoint preset tokenlari bo'ylab
    PATROL_SWEEP   = "sweep"     # pan_min..pan_max avtomatik gradus sweep
    PATROL_HYBRID  = "hybrid"    # preset bor bo'lsa preset, yo'q bo'lsa sweep
    PATROL_CHOICES = [
        (PATROL_DEFAULT, "Global sozlama"),
        (PATROL_OFF, "O'chiq (statik)"),
        (PATROL_PRESET, "Preset bo'ylab"),
        (PATROL_SWEEP, "Avtomatik sweep"),
        (PATROL_HYBRID, "Gibrid"),
    ]
    patrol_mode = models.CharField(max_length=16, choices=PATROL_CHOICES,
                                   default=PATROL_DEFAULT)

    # Sweep rejimi parametrlari (gradus)
    patrol_pan_min = models.FloatField(default=-0.6,
                                       help_text="ONVIF normalized pan [-1..1] chap chegara")
    patrol_pan_max = models.FloatField(default=0.6,
                                       help_text="ONVIF normalized pan [-1..1] o'ng chegara")
    patrol_tilt = models.FloatField(default=0.0,
                                    help_text="ONVIF normalized tilt [-1..1]")
    patrol_zoom = models.FloatField(default=0.0,
                                    help_text="ONVIF normalized zoom [0..1]")
    patrol_steps = models.IntegerField(default=3,
                                       help_text="Sweep nechta nuqtaga bo'linadi")
    patrol_dwell_seconds = models.FloatField(default=3.0,
                                             help_text="Har nuqtada necha soniya turadi (AI shu paytda taniydi)")

    class Meta:
        db_table = "cameras"


class CameraPatrolPoint(BaseModel):
    """
    'preset' rejimi uchun bitta patrul nuqtasi.
    Kamera shu tartibda preset tokenlar bo'ylab aylanadi.
    """
    camera = models.ForeignKey(Camera, on_delete=models.CASCADE, related_name="patrol_points")
    order = models.IntegerField(default=0, help_text="Aylanish tartibi (0,1,2...)")
    preset_token = models.CharField(max_length=64, help_text="ONVIF preset token")
    label = models.CharField(max_length=64, null=True, blank=True,
                             help_text="Masalan: chap_qator, markaz, o'ng_qator")
    dwell_seconds = models.FloatField(null=True, blank=True,
                                      help_text="Bo'sh bo'lsa Camera.patrol_dwell_seconds ishlatiladi")

    class Meta:
        db_table = "camera_patrol_points"
        ordering = ["camera_id", "order"]
        constraints = [
            models.UniqueConstraint(fields=["camera", "order"], name="camera_patrol_order_uniq"),
        ]

    def __str__(self):
        return f"cam={self.camera_id} #{self.order} {self.label or self.preset_token}"


class AuditoriumCamera(models.Model):
    auditorium = models.ForeignKey(Auditorium, on_delete=models.CASCADE, related_name="auditorium_cameras")
    camera = models.ForeignKey(Camera, on_delete=models.CASCADE, related_name="camera_auditoriums")

    class Meta:
        db_table = "auditorium_camera"
        constraints = [
            models.UniqueConstraint(fields=["auditorium", "camera"], name="auditorium_camera_uniq"),
        ]


class CameraROI(BaseModel):
    image_url = models.TextField(null=True, blank=True)
    roi_x = models.IntegerField()
    roi_y = models.IntegerField()
    roi_width = models.IntegerField()
    roi_height = models.IntegerField()
    frame_width = models.IntegerField(null=True, blank=True)
    frame_height = models.IntegerField(null=True, blank=True)
    camera = models.OneToOneField(Camera, on_delete=models.CASCADE, related_name="roi")
    updated_by = models.ForeignKey(
        "common.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_rois",
    )

    class Meta:
        db_table = "camera_rois"


class SmartCamera(BaseModel):
    name = models.TextField()
    device_id = models.TextField(unique=True)
    device_mac = models.TextField(unique=True)
    lib_platform_version = models.TextField(null=True, blank=True)
    software_version = models.TextField(null=True, blank=True)
    lib_ai_version = models.TextField(null=True, blank=True)
    device_ip = models.TextField(null=True, blank=True)
    time_stamp = models.TextField(null=True, blank=True)
    rtsp_url_format = models.CharField(max_length=16, null=True, blank=True)
    hearbeat = models.TextField(null=True, blank=True)
    login = EncryptedTextField()
    password = EncryptedTextField()
    device_name = models.TextField(null=True, blank=True)
    device_lan = models.TextField(null=True, blank=True)
    device_lon = models.TextField(null=True, blank=True)
    distance = models.FloatField(null=True, blank=True)
    port = models.IntegerField(null=True, blank=True)
    path = models.TextField(null=True, blank=True)
    channel = models.IntegerField(null=True, blank=True)
    is_main_stream = models.BooleanField(null=True, blank=True)
    auditorium = models.ForeignKey(Auditorium, on_delete=models.CASCADE, related_name="smart_cameras")

    class Meta:
        db_table = "smart_cameras"