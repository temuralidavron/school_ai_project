# Face detection pipeline — DeepStream o'rniga sodda Python + InsightFace
# Asosiy image loyihaning o'zi bilan bir xil (CUDA 12.6 + cuDNN)
# nvinfer/GStreamer kerak emas: OpenCV NVDEC + InsightFace buffalo_l (det only)

FROM nvidia/cuda:12.6.3-cudnn-runtime-ubuntu24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_EXTRA_INDEX_URL=https://pypi.org/simple/ \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_TRUSTED_HOST="mirrors.aliyun.com pypi.org files.pythonhosted.org" \
    INSIGHTFACE_HOME=/root/.insightface

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip \
    libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Ubuntu 24.04 Python 3.12 da --break-system-packages kerak (PEP 668, container ichida xavfsiz)
RUN pip3 install --no-cache-dir --break-system-packages \
    numpy \
    opencv-python-headless \
    kafka-python-ng>=2.2.3 \
    insightface

# CPU onnxruntime ni GPU versiyasiga almashtirish
# pypi.org dan to'g'ridan-to'g'ri — Aliyun mirrorda Python 3.12 wheeli yo'q
RUN pip3 install --no-cache-dir --break-system-packages \
    --index-url https://pypi.org/simple/ \
    onnxruntime-gpu==1.25.0

WORKDIR /workspace

ENTRYPOINT ["python3", "/workspace/pipeline/main.py"]
