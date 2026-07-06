
"""Kafka producer — Kafka yuborishni oddiy interfeys orqali yashirish."""
import json
import logging
import time

log = logging.getLogger(__name__)


class KafkaClient:
    # Pipeline ishga tushgan vaqt (sekund) — har restart yangi qiymat
    SESSION_ID = int(time.time())

    def __init__(self, bootstrap: str, topic: str):
        self._topic    = topic
        self._producer = None
        if not bootstrap:
            log.warning("KAFKA_BOOTSTRAP bo'sh — Kafka off")
            return
        try:
            from kafka import KafkaProducer
            for attempt in range(15):
                try:
                    self._producer = KafkaProducer(
                        bootstrap_servers=bootstrap,
                        value_serializer=lambda v: json.dumps(v).encode(),
                        acks=1,
                        linger_ms=10,
                        compression_type=None,
                    )
                    log.info("Kafka ulandi: %s", bootstrap)
                    return
                except Exception as exc:
                    log.warning("Kafka kutilmoqda (%d/15): %s", attempt + 1, exc)
                    time.sleep(2)
        except ImportError:
            log.error("kafka-python-ng o'rnatilmagan")

    def send(self, camera_id: int, frame_id: int, track_id: int,
             bbox: dict, score: float, embedding: list[float],
             face_crop: str | None = None) -> bool:
        if not self._producer:
            return False
        msg = {
            "ts":         time.time(),
            "camera_id":  camera_id,
            "frame_id":   frame_id,
            "track_id":   track_id,
            "session_id": self.SESSION_ID,  # har restart yangi → track_key unique
            "bbox":       bbox,
            "confidence": score,
            "embedding":  embedding,
        }
        if face_crop:
            msg["face_crop"] = face_crop
        try:
            self._producer.send(self._topic, msg)
            return True
        except Exception as exc:
            log.debug("Kafka yuborish xatosi: %s", exc)
            return False

    def flush(self):
        if self._producer:
            self._producer.flush(timeout=5)
