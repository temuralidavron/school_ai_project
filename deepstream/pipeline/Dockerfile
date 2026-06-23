# DeepStream pipeline container — school_attendace_v1 ichida
# Mavjud tizimga qo'shimcha: faqat yuz topish + Kafka producer
# Recognition/davomat yozish Django consumer'da (apps/cameras/management/commands/kafka_consumer.py)

FROM nvcr.io/nvidia/deepstream:7.1-gc-triton-devel

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip python3-gi python3-gi-cairo \
    gir1.2-gstreamer-1.0 libgirepository1.0-dev libcairo2-dev pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt

# Pipeline kodi va configlar volume orqali mount qilinadi (docker-compose.yml)
ENTRYPOINT ["python3", "/workspace/pipeline/main.py"]
