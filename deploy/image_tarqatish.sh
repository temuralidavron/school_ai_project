#!/bin/bash
# =============================================================================
# IMAGE TARQATISH — har maktabda 30-50 daqiqa build o'rniga tayyor image.
#
#   bash deploy/image_tarqatish.sh export                # shu serverda to'plam yasash
#   bash deploy/image_tarqatish.sh import /media/usb/school_ai_dist
#                                                        # maktab serverida yuklash
#   bash deploy/image_tarqatish.sh push  registry.host:5000   # registry'ga
#   bash deploy/image_tarqatish.sh pull  registry.host:5000   # registry'dan
#
# EXPORT nima yig'adi (jami ~15-20 GB, 64 GB USB ga sig'adi):
#   - school_ai, school_ai_ds3 va infra image'lar (postgres, kafka, minio, mc)
#   - buffalo_l modellari (docker volume'dan) — maktabda internet kerak emas
#   - deepstream_v3/engines/*.onnx (GPU-mustaqil) va *.engine (GPU nomi bilan
#     belgilanadi: bir xil GPU bo'lsa engine ham tayyor, boshqa bo'lsa
#     start.sh o'zi ~1-2 daqiqada quradi)
#   - sha256 nazorat summalari + manifest (git commit, sana, GPU)
#
# IMPORT: summalarni tekshiradi -> image'larni yuklaydi -> buffalo_l ni
# volume'ga tiklaydi -> onnx'ni har doim, engine'ni GPU mos kelsagina
# ko'chiradi. Keyin `bash deploy/start.sh rtsp` build bosqichlarini
# "bor OK" deb o'tkazib yuboradi.
# =============================================================================
set -u
cd "$(dirname "$0")/.."

CMD="${1:-}"; shift 2>/dev/null || true
DIR="dist_images"
VOL="school_ai_project_insightface_models"
# school_ai_ds3 katta (~38 GB) — zstd -3 T0 bilan ~15-20 daqiqada siqiladi
IMAGES="school_ai:latest school_ai_ds3:latest pgvector/pgvector:pg16 apache/kafka:latest minio/minio:latest minio/mc:latest"

case "$CMD" in
  export)
    [ "${1:-}" = "--out" ] && DIR="$2"
    mkdir -p "$DIR"
    echo "============================================================"
    echo " EXPORT -> $DIR/"
    echo "============================================================"

    GPU=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
    {
      echo "yaratilgan: $(date '+%Y-%m-%d %H:%M')"
      echo "git_commit: $(git rev-parse --short HEAD 2>/dev/null || echo '?')"
      echo "gpu: ${GPU:-nomalum}"
      echo "images: $IMAGES"
    } > "$DIR/manifest.txt"
    cat "$DIR/manifest.txt" | sed 's/^/  /'
    echo

    for IMG in $IMAGES; do
      F="$DIR/$(echo "$IMG" | tr '/:' '__').tar.zst"
      if [ -s "$F" ]; then echo "  $IMG: bor, o'tkazildi"; continue; fi
      if ! docker image inspect "$IMG" >/dev/null 2>&1; then
        echo "  XATO: $IMG lokalda yo'q — avval build/pull qiling"; exit 1
      fi
      echo "  $IMG siqilmoqda..."
      docker save "$IMG" | zstd -T0 -3 -q -o "$F" || { echo "  XATO: $IMG"; rm -f "$F"; exit 1; }
      ls -la "$F" | awk '{printf "    %.1f GB\n", $5/1073741824}'
    done

    echo "  buffalo_l modellari (volume'dan)..."
    if docker run --rm -v "$VOL":/m alpine test -d /m/models/buffalo_l 2>/dev/null; then
      docker run --rm -v "$VOL":/m alpine tar -cf - -C /m models/buffalo_l \
        | zstd -T0 -3 -q -o "$DIR/insightface_models.tar.zst"
      ls -la "$DIR/insightface_models.tar.zst" | awk '{printf "    %.0f MB\n", $5/1048576}'
    else
      echo "    DIQQAT: volume'da buffalo_l yo'q — maktabda internetdan yuklanadi"
    fi

    if ls deepstream_v3/engines/*.onnx >/dev/null 2>&1; then
      echo "  engines (onnx GPU-mustaqil, engine: ${GPU:-?})..."
      tar -cf - -C deepstream_v3 engines | zstd -T0 -3 -q -o "$DIR/engines.tar.zst"
    fi

    echo "  nazorat summalari..."
    ( cd "$DIR" && sha256sum *.tar.zst > SHA256SUMS )
    echo
    echo "============================================================"
    du -sh "$DIR" | awk '{print " TAYYOR: "$1"  ->  "$2"/"}'
    echo " Maktabga: USB ga nusxalang, u yerda:"
    echo "   bash deploy/image_tarqatish.sh import /media/usb/$DIR"
    echo "============================================================"
    ;;

  import)
    SRC="${1:-$DIR}"
    [ -d "$SRC" ] || { echo "XATO: papka topilmadi: $SRC"; exit 1; }
    echo "============================================================"
    echo " IMPORT <- $SRC/"
    echo "============================================================"
    [ -f "$SRC/manifest.txt" ] && sed 's/^/  /' "$SRC/manifest.txt" && echo

    echo "  summalar tekshirilmoqda (bir necha daqiqa)..."
    ( cd "$SRC" && sha256sum -c SHA256SUMS --quiet ) || { echo "  XATO: fayl buzilgan — qayta nusxalang"; exit 1; }
    echo "    OK"

    for F in "$SRC"/*.tar.zst; do
      B=$(basename "$F")
      case "$B" in insightface_models.tar.zst|engines.tar.zst) continue ;; esac
      echo "  yuklanmoqda: $B ..."
      zstd -dc "$F" | docker load | sed 's/^/    /'
    done

    if [ -f "$SRC/insightface_models.tar.zst" ]; then
      echo "  buffalo_l -> volume ($VOL)..."
      docker volume create "$VOL" >/dev/null
      zstd -dc "$SRC/insightface_models.tar.zst" \
        | docker run --rm -i -v "$VOL":/m alpine tar -xf - -C /m
      echo "    OK"
    fi

    if [ -f "$SRC/engines.tar.zst" ]; then
      GPU_MAN=$(grep '^gpu:' "$SRC/manifest.txt" 2>/dev/null | cut -d' ' -f2-)
      GPU_BU=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
      mkdir -p deepstream_v3/engines
      if [ -n "$GPU_BU" ] && [ "$GPU_MAN" = "$GPU_BU" ]; then
        echo "  engines: GPU mos ($GPU_BU) — onnx + engine ko'chirildi"
        zstd -dc "$SRC/engines.tar.zst" | tar -xf - -C deepstream_v3
      else
        # engine GPU arxitekturasiga bog'langan — mos kelmasa faqat onnx
        # olinadi, engine'ni start.sh trtexec bilan o'zi quradi (~1-2 daq)
        echo "  engines: GPU boshqa (to'plam: ${GPU_MAN:-?}, bu server: ${GPU_BU:-?})"
        echo "           faqat onnx ko'chirildi — engine start.sh da quriladi"
        zstd -dc "$SRC/engines.tar.zst" | tar -xf - -C deepstream_v3 --wildcards 'engines/*.onnx' 2>/dev/null || true
      fi
    fi

    echo
    echo "============================================================"
    echo " IMPORT TUGADI. Endi:"
    echo "   cp .env.example .env   # org_id/parollarni yozing (birinchi marta)"
    echo "   bash deploy/start.sh rtsp"
    echo "============================================================"
    ;;

  push|pull)
    REG="${1:-}"
    [ -n "$REG" ] || { echo "XATO: registry manzili kerak, masalan: $CMD registry.host:5000"; exit 1; }
    for IMG in school_ai:latest school_ai_ds3:latest; do
      if [ "$CMD" = "push" ]; then
        docker tag "$IMG" "$REG/$IMG" && docker push "$REG/$IMG" || exit 1
      else
        docker pull "$REG/$IMG" && docker tag "$REG/$IMG" "$IMG" || exit 1
      fi
      echo "  $CMD OK: $IMG"
    done
    ;;

  *)
    sed -n '3,23p' "$0" | sed 's/^# \?//'
    exit 1
    ;;
esac
