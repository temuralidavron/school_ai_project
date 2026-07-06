# To'liq DeepStream 8.0 pipeline — nvinfer TRT (sm_120) + pyds Python probe
# Base entrypoint buyruqni yutadi — o'zimizniki bilan almashtiriladi.

FROM nvcr.io/nvidia/deepstream:8.0-gc-triton-devel

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1

# pyds 1.2.2 — DS 8.0 / Python 3.12 rasmiy wheel (GitHub releases)
RUN pip3 install --break-system-packages --no-cache-dir \
    "https://github.com/NVIDIA-AI-IOT/deepstream_python_apps/releases/download/v1.2.2/pyds-1.2.2-cp312-cp312-linux_x86_64.whl" \
    opencv-python-headless \
    "kafka-python-ng>=2.2.3"

# ORT GPU — B3 gibrid ArcFace uchun (embedding Python probe'da)
RUN pip3 install --break-system-packages --no-cache-dir onnxruntime-gpu

WORKDIR /ds3
COPY pipeline/ ./pipeline/
COPY configs/  ./configs/

ENV PGIE_CONFIG=/ds3/configs/pgie_det10g.txt

ENTRYPOINT ["python3", "/ds3/pipeline/main.py"]
