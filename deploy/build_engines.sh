#!/bin/bash
# =============================================================================
# TensorRT engine qurish — YANGI SERVERDA BIR MARTA BAJARILADI.
#
#   bash deploy/build_engines.sh
#
# NEGA KERAK: deepstream_v3/engines/ .gitignore da (82-qator), ya'ni GitHub da
# YO'Q. Engine fayllari GPU arxitekturasiga bog'langan (RTX 5080 = sm_120) —
# boshqa mashinadan nusxa ko'chirish ishonchsiz, shuning uchun joyida quriladi.
#
# Yana bir sabab: configs/pgie_det10g_1280.txt da faqat `model-engine-file=` bor,
# `onnx-file=` YO'Q. Ya'ni engine bo'lmasa nvinfer uni O'ZI QURA OLMAYDI —
# pipeline ishga tushmaydi.
#
# ZANJIR (ikki konteyner, chunki vositalar bo'lingan):
#   1) school_ai:latest      — onnx paketi BOR, trtexec yo'q
#      -> make_input_size.py bilan det_10g.onnx dan 1280 lik ONNX yasaydi
#   2) school_ai_ds3:latest  — trtexec BOR, onnx paketi yo'q
#      -> trtexec bilan FP16 engine quradi
#
# ArcFace uchun engine KERAK EMAS: v3 da w600k_r50.onnx to'g'ridan ONNX Runtime
# GPU bilan ishlaydi (deepstream_v3/pipeline/arcface_runner.py).
# =============================================================================
set -e
cd "$(dirname "$0")/.."

ENG_DIR="$(pwd)/deepstream_v3/engines"
VOL="school_ai_project_insightface_models"
DET_SZ="${DET_SZ:-1280}"
ONNX_OUT="det_10g_${DET_SZ}_batched.onnx"
ENGINE_OUT="det_10g_${DET_SZ}_fp16.engine"

mkdir -p "$ENG_DIR"

echo "============================================================"
echo " TensorRT engine qurish — det_10g @ ${DET_SZ}x${DET_SZ} FP16"
echo "============================================================"
echo "  chiqish: deepstream_v3/engines/$ENGINE_OUT"
echo

# ─── 0. Shartlar ─────────────────────────────────────────────────────────────
for img in school_ai:latest school_ai_ds3:latest; do
  docker image inspect "$img" >/dev/null 2>&1 || {
    echo "  XATO: $img topilmadi. Avval: docker compose build"; exit 1; }
done
nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 | sed 's/^/  GPU: /' || {
  echo "  XATO: GPU ko'rinmayapti — deploy/server_setup.sh ni bajaring"; exit 1; }

if [ -f "$ENG_DIR/$ENGINE_OUT" ]; then
  echo "  $ENGINE_OUT allaqachon bor — qayta qurish uchun avval o'chiring."
  ls -la "$ENG_DIR/$ENGINE_OUT" | awk '{printf "    %s  %.1f MB\n", $NF, $5/1048576}'
  exit 0
fi

# ─── 1. InsightFace modellari (volume) ───────────────────────────────────────
echo "[1/3] InsightFace buffalo_l modellari"
if ! docker run --rm -v "$VOL":/m alpine test -f /m/models/buffalo_l/det_10g.onnx 2>/dev/null; then
  echo "      det_10g.onnx yo'q — InsightFace yuklab oladi (~325 MB, internet kerak)..."
  docker run --rm --gpus all -v "$VOL":/root/.insightface \
    --entrypoint python3.14 school_ai:latest -c "
from insightface.app import FaceAnalysis
FaceAnalysis(name='buffalo_l').prepare(ctx_id=0, det_size=(640,640))
print('  modellar yuklandi')" 2>&1 | tail -2 | sed 's/^/      /'
fi
docker run --rm -v "$VOL":/m alpine ls -la /m/models/buffalo_l/det_10g.onnx \
  | awk '{printf "      OK  det_10g.onnx  %.1f MB\n", $5/1048576}'
echo

# ─── 2. ONNX ni DET_SZ ga qayta eksport (onnx paketi school_ai da) ───────────
echo "[2/3] det_10g.onnx -> ${DET_SZ}x${DET_SZ} ONNX (make_input_size.py)"
if [ -f "$ENG_DIR/$ONNX_OUT" ]; then
  echo "      $ONNX_OUT allaqachon bor — o'tkazildi"
else
  docker run --rm \
    -v "$VOL":/insightface:ro \
    -v "$ENG_DIR":/out \
    -v "$(pwd)/deepstream_v3/tools":/tools:ro \
    --entrypoint python3.14 school_ai:latest \
    /tools/make_input_size.py /insightface/models/buffalo_l/det_10g.onnx "/out/$ONNX_OUT" "$DET_SZ" \
    2>&1 | tail -4 | sed 's/^/      /'
  [ -f "$ENG_DIR/$ONNX_OUT" ] || { echo "      XATO: ONNX yaratilmadi"; exit 1; }
  ls -la "$ENG_DIR/$ONNX_OUT" | awk '{printf "      OK  %s  %.1f MB\n", $NF, $5/1048576}'
fi
echo

# ─── 3. trtexec bilan FP16 engine (trtexec ds3 da) ───────────────────────────
echo "[3/3] TensorRT engine (FP16) — bu 5-15 daqiqa olishi mumkin"
# DIQQAT: make_input_size.py STATIK shape li ONNX yasaydi ([1,3,DET_SZ,DET_SZ]).
# Statik ONNX ga --minShapes/--optShapes/--maxShapes BERILMAYDI — trtexec
# "Network And Config setup failed" bilan yiqiladi. (Eski 640 lik ONNX dynamic
# edi: [1,3,?,?] — o'sha yerda shape berish kerak edi, shundan chalkashlik.)
docker run --rm --gpus all \
  -v "$ENG_DIR":/engines \
  --entrypoint /usr/bin/trtexec school_ai_ds3:latest \
  --onnx="/engines/$ONNX_OUT" \
  --saveEngine="/engines/$ENGINE_OUT" \
  --fp16 \
  2>&1 | grep -iE "building|completed|passed|failed|error|engine was|throughput" | tail -6 | sed 's/^/      /'

echo
if [ -f "$ENG_DIR/$ENGINE_OUT" ]; then
  ls -la "$ENG_DIR/$ENGINE_OUT" | awk '{printf "  TAYYOR: %s  %.1f MB\n", $NF, $5/1048576}'
  echo
  echo "  Endi pipeline ishga tushadi:"
  echo "    docker compose --profile deepstream up -d ds3"
  echo "    docker logs -f school_ai_ds3"
else
  echo "  XATO: engine yaratilmadi. Yuqoridagi trtexec chiqishini ko'ring."
  echo "  Ko'p uchraydigan sabab: GPU xotirasi yetmasligi — boshqa konteynerlarni"
  echo "  to'xtatib qayta urinib ko'ring (docker compose stop ds3 cameras)."
  exit 1
fi
