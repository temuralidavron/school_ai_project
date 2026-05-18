"""
ONVIF orqali PTZ kamerani boshqarish.

Qo'llab-quvvatlanadigan kameralar:
  - SONY 8.5MP (VISCA over IP, ONVIF)
  - ONVIF-mos istalgan PTZ kamera

Ishlatish:
    service = PtzService(camera)
    service.goto_preset("1")        # preset 1 ga boring
    service.stop()                  # PTZ harakatini to'xtatish
    presets = service.list_presets()
    service.save_preset("1", "Dars_pozitsiya")
"""
import logging
import socket

logger = logging.getLogger(__name__)

_ONVIF_DEFAULT_PORT = 80
_VISCA_DEFAULT_PORT = 52381  # VISCA over IP standart porti


# ─── ONVIF PTZ ────────────────────────────────────────────────────────────────

class PtzService:
    """
    ONVIF Media + PTZ servislar orqali kamerani boshqaradi.

    Camera modelida quyidagi maydonlar bo'lishi kerak:
        ip_address, username (decrypted), password (decrypted),
        onvif_port (int, default 80)
    """

    def __init__(self, camera):
        self.camera = camera
        self._onvif_cam = None
        self._ptz = None
        self._media = None
        self._profile_token = None

    def _connect(self):
        if self._onvif_cam is not None:
            return
        try:
            from onvif import ONVIFCamera
        except ImportError:
            raise RuntimeError(
                "onvif-zeep o'rnatilmagan. "
                "pip install onvif-zeep"
            )

        port = getattr(self.camera, "onvif_port", None) or _ONVIF_DEFAULT_PORT
        cam = ONVIFCamera(
            self.camera.ip_address,
            port,
            self.camera.username,
            self.camera.password,
        )
        self._onvif_cam = cam
        self._media = cam.create_media_service()
        self._ptz = cam.create_ptz_service()
        profiles = self._media.GetProfiles()
        if not profiles:
            raise RuntimeError(f"cam={self.camera.id}: ONVIF profil topilmadi")
        self._profile_token = profiles[0].token
        logger.info("ONVIF ulandi: cam=%s  ip=%s:%s  profil=%s",
                    self.camera.id, self.camera.ip_address, port, self._profile_token)

    # ─── Public API ──────────────────────────────────────────────────────────

    def list_presets(self) -> list[dict]:
        """Barcha saqlangan preset ro'yxatini qaytaradi."""
        self._connect()
        try:
            presets = self._ptz.GetPresets({"ProfileToken": self._profile_token})
            result = []
            for p in (presets or []):
                result.append({
                    "token": p.token,
                    "name": getattr(p, "Name", ""),
                })
            logger.info("cam=%s presetlar: %s", self.camera.id, result)
            return result
        except Exception as e:
            logger.error("cam=%s list_presets xato: %s", self.camera.id, e)
            raise

    def goto_preset(self, preset_token: str, speed: float = 0.5):
        """Berilgan preset ga o'tadi."""
        self._connect()
        try:
            self._ptz.GotoPreset({
                "ProfileToken": self._profile_token,
                "PresetToken": preset_token,
                "Speed": {
                    "PanTilt": {"x": speed, "y": speed},
                    "Zoom": {"x": speed},
                },
            })
            logger.info("cam=%s → preset=%s", self.camera.id, preset_token)
        except Exception as e:
            logger.error("cam=%s goto_preset=%s xato: %s", self.camera.id, preset_token, e)
            raise

    def absolute_move(self, pan: float, tilt: float, zoom: float = 0.0, speed: float = 0.5):
        """
        Normalized absolute pozitsiyaga o'tadi (sweep rejimi uchun).
        pan/tilt: [-1..1], zoom: [0..1]
        """
        self._connect()
        try:
            self._ptz.AbsoluteMove({
                "ProfileToken": self._profile_token,
                "Position": {
                    "PanTilt": {"x": float(pan), "y": float(tilt)},
                    "Zoom": {"x": float(zoom)},
                },
                "Speed": {
                    "PanTilt": {"x": speed, "y": speed},
                    "Zoom": {"x": speed},
                },
            })
            logger.debug("cam=%s absolute_move pan=%.3f tilt=%.3f zoom=%.3f",
                         self.camera.id, pan, tilt, zoom)
        except Exception as e:
            logger.error("cam=%s absolute_move xato: %s", self.camera.id, e)
            raise

    def save_preset(self, preset_token: str, preset_name: str = "") -> str:
        """Joriy pozitsiyani preset sifatida saqlaydi."""
        self._connect()
        try:
            req = {"ProfileToken": self._profile_token}
            if preset_token:
                req["PresetToken"] = preset_token
            if preset_name:
                req["PresetName"] = preset_name
            result = self._ptz.SetPreset(req)
            token = getattr(result, "PresetToken", preset_token)
            logger.info("cam=%s preset saqlandi: token=%s name=%s", self.camera.id, token, preset_name)
            return token
        except Exception as e:
            logger.error("cam=%s save_preset xato: %s", self.camera.id, e)
            raise

    def stop(self):
        """PTZ harakatini to'xtatadi."""
        self._connect()
        try:
            self._ptz.Stop({
                "ProfileToken": self._profile_token,
                "PanTilt": True,
                "Zoom": True,
            })
        except Exception as e:
            logger.warning("cam=%s stop xato: %s", self.camera.id, e)

    def get_status(self) -> dict:
        """Joriy PTZ pozitsiyasini qaytaradi."""
        self._connect()
        try:
            status = self._ptz.GetStatus({"ProfileToken": self._profile_token})
            pos = status.Position
            return {
                "pan": float(pos.PanTilt.x),
                "tilt": float(pos.PanTilt.y),
                "zoom": float(pos.Zoom.x),
                "moving": (
                    status.MoveStatus.PanTilt != "IDLE"
                    or status.MoveStatus.Zoom != "IDLE"
                ),
            }
        except Exception as e:
            logger.error("cam=%s get_status xato: %s", self.camera.id, e)
            raise

    def get_rtsp_url(self, stream: str = "RtspUnicast", protocol: str = "RTSP") -> str | None:
        """
        ONVIF orqali RTSP URL oladi (sub-stream uchun stream_index=1).
        """
        self._connect()
        try:
            profiles = self._media.GetProfiles()
            for i, profile in enumerate(profiles):
                req = self._media.create_type("GetStreamUri")
                req.StreamSetup = {
                    "Stream": stream,
                    "Transport": {"Protocol": protocol},
                }
                req.ProfileToken = profile.token
                uri = self._media.GetStreamUri(req)
                logger.info("cam=%s profil[%d] RTSP: %s", self.camera.id, i, uri.Uri)
            # birinchi profil
            req = self._media.create_type("GetStreamUri")
            req.StreamSetup = {"Stream": stream, "Transport": {"Protocol": protocol}}
            req.ProfileToken = self._profile_token
            uri = self._media.GetStreamUri(req)
            return uri.Uri
        except Exception as e:
            logger.error("cam=%s get_rtsp_url xato: %s", self.camera.id, e)
            return None

    def lock_to_attendance_position(self, preset_token: str | None = None):
        """
        Kamerani davomat uchun to'g'ri pozitsiyaga qulflaydi.
        preset_token: Camera.ptz_preset_token (DB dan olingan)
        """
        token = preset_token or getattr(self.camera, "ptz_preset_token", None)
        if not token:
            logger.warning("cam=%s ptz_preset_token yo'q — lock qilinmadi", self.camera.id)
            return False
        self.goto_preset(token)
        return True


# ─── VISCA over IP (zaxira) ───────────────────────────────────────────────────

class ViscaClient:
    """
    UDP orqali VISCA over IP buyruqlari.
    ONVIF ishlamagan hollarda zaxira sifatida.

    VISCA protokoli: kamera pozitsiyani belgilangan preset ga qo'yadi.
    """

    def __init__(self, ip: str, port: int = _VISCA_DEFAULT_PORT, timeout: float = 2.0):
        self.ip = ip
        self.port = port
        self.timeout = timeout
        self._sock: socket.socket | None = None

    def _get_sock(self) -> socket.socket:
        if self._sock is None:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(self.timeout)
            self._sock = s
        return self._sock

    def _send(self, data: bytes) -> bytes | None:
        try:
            sock = self._get_sock()
            sock.sendto(data, (self.ip, self.port))
            reply, _ = sock.recvfrom(1024)
            return reply
        except socket.timeout:
            return None
        except Exception as e:
            logger.error("VISCA %s:%s xato: %s", self.ip, self.port, e)
            return None

    def recall_preset(self, preset_num: int):
        """
        Preset recall (0-based: preset 1 = 0x00).
        VISCA: 81 01 04 3F 02 <preset> FF
        """
        pn = max(0, min(preset_num - 1, 127))
        cmd = bytes([0x81, 0x01, 0x04, 0x3F, 0x02, pn, 0xFF])
        reply = self._send(cmd)
        if reply:
            logger.info("VISCA %s preset=%d recall OK", self.ip, preset_num)
        else:
            logger.warning("VISCA %s preset=%d javob yo'q", self.ip, preset_num)

    def stop(self):
        """VISCA Stop: 81 01 06 01 03 03 FF"""
        self._send(bytes([0x81, 0x01, 0x06, 0x01, 0x03, 0x03, 0xFF]))

    def close(self):
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
