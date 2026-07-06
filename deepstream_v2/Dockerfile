# Haqiqiy NVIDIA DeepStream 7.1 — yuz tanish davomat pipeline
# nvstreammux (NVDEC) + nvtracker (GPU) + Python probe (ORT GPU det+recog)
# RTX 5080 (sm_120): TRT 10.3 qo'llab-quvvatlamaydi → onnxruntime-gpu ishlatiladi

FROM nvcr.io/nvidia/deepstream:7.1-gc-triton-devel

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    GST_DEBUG=0

# Tizim paketlar
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-gi python3-gi-cairo gir1.2-gst-rtsp-server-1.0 \
    python3-gst-1.0 \
    lz4 liblz4-dev \
    && rm -rf /var/lib/apt/lists/*

# pyds (DeepStream Python bindings) — DS 7.1 / Python 3.10 / x86_64
RUN pip3 install --no-cache-dir \
    "https://github.com/NVIDIA-AI-IOT/deepstream_python_apps/releases/download/v1.2.0/pyds-1.2.0-cp310-cp310-linux_x86_64.whl"

# Python paketlar
RUN pip3 install --no-cache-dir \
    numpy \
    opencv-python-headless \
    "kafka-python-ng>=2.2.3" \
    lz4 \
    onnx

# GPU ONNX Runtime — DS 7.1 Python versiyasida eng yuqori mavjud
RUN pip3 install --no-cache-dir \
    --index-url https://pypi.org/simple/ \
    "onnxruntime-gpu==1.23.2"

WORKDIR /ds_pipeline

COPY pipeline/ ./pipeline/
COPY configs/  ./configs/
COPY scripts/  ./scripts/

RUN chmod +x /ds_pipeline/scripts/build_engines.sh

ENV MODELS_DIR=/root/.insightface/models \
    ENGINES_DIR=/engines \
    PGIE_CONFIG=/ds_pipeline/configs/pgie_det10g.txt \
    TRACKER_CONFIG=/ds_pipeline/configs/tracker_nvdcf.txt

ENTRYPOINT ["python3", "/ds_pipeline/pipeline/main.py"]
