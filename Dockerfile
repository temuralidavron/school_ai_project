# ─── school_attendace_v1 — GPU (NVIDIA RTX 5080) uchun ────────────────────────
# onnxruntime-gpu 1.25 → CUDA 12.x + cuDNN 9.x talab qiladi.
# Hostda nvidia-container-toolkit o'rnatilgan bo'lishi shart.

FROM nvidia/cuda:12.6.3-cudnn-runtime-ubuntu24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Tashkent \
    # PyPI CDN (Fastly) O'zbekistondan sekin — Aliyun mirror (Tashkent'dan tez),
    # pypi.org zaxira sifatida (mirror'da topilmasa)
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_EXTRA_INDEX_URL=https://pypi.org/simple/ \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10 \
    PIP_TRUSTED_HOST="mirrors.aliyun.com pypi.org files.pythonhosted.org"

# ─── Tizim paketlari + Python 3.14 (deadsnakes) ───────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        software-properties-common \
        ca-certificates \
        curl \
        tzdata \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
        python3.14 \
        python3.14-venv \
        python3.14-dev \
        build-essential \
        cron \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        libpq5 \
    && ln -sf /usr/share/zoneinfo/$TZ /etc/localtime \
    && rm -rf /var/lib/apt/lists/*

# pip (3.14 uchun)
RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python3.14

WORKDIR /app

# ─── Python kutubxonalar ──────────────────────────────────────────────────────
# Avval requirements (Docker layer cache uchun)
COPY requirements.txt .
# --ignore-installed: bazaviy image'dagi apt-cryptography (RECORD yo'q) ni
#   o'chirmasdan, bizning versiyani Python 3.14 site-packages'ga o'rnatadi.
RUN python3.14 -m pip install --upgrade pip setuptools wheel \
    && python3.14 -m pip install --ignore-installed -r requirements.txt \
    # CPU onnxruntime ni GPU versiyasiga almashtirish
    && python3.14 -m pip uninstall -y onnxruntime \
    && python3.14 -m pip install onnxruntime-gpu==1.25.0

# ─── Loyiha kodi ──────────────────────────────────────────────────────────────
COPY . .

# entrypoint skriptlar
RUN chmod +x docker/entrypoint-web.sh docker/entrypoint-cameras.sh docker/entrypoint-cron.sh

# InsightFace buffalo_l modellari shu papkaga yuklanadi (volume mount qilinadi)
ENV INSIGHTFACE_HOME=/root/.insightface

EXPOSE 8000

# Default: web (compose da cameras uchun override qilinadi)
CMD ["./docker/entrypoint-web.sh"]
