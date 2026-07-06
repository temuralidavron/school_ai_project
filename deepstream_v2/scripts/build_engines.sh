#!/bin/bash
# det_10g.onnx va w600k_r50.onnx → TensorRT engine (FP16)
# DeepStream konteyner ichida ishga tushiriladi
# Maqsad: /models/engines/ papkasiga engine fayllar yaratish

set -e

MODELS_DIR="${MODELS_DIR:-/root/.insightface/models}"
ENGINES_DIR="${ENGINES_DIR:-/engines}"
mkdir -p "$ENGINES_DIR"

echo "=========================================="
echo " TensorRT Engine Build"
echo " GPU: $(nvidia-smi --query-gpu=name --format=csv,noheader)"
echo " TRT: $(trtexec --version 2>&1 | head -1)"
echo "=========================================="

# ── det_10g — yuz topuvchi (SCRFD-10G) ────────────────────────────────────────
DET_ONNX="$MODELS_DIR/buffalo_l/det_10g.onnx"
DET_ENG="$ENGINES_DIR/det_10g_b1_fp16.engine"

if [ ! -f "$DET_ENG" ]; then
    echo "[1/2] det_10g.onnx → TRT engine (FP16, batch=1, 640x640)..."
    trtexec \
        --onnx="$DET_ONNX" \
        --saveEngine="$DET_ENG" \
        --fp16 \
        --optShapes="input.1:1x3x640x640" \
        --minShapes="input.1:1x3x640x640" \
        --maxShapes="input.1:1x3x640x640" \
        --workspace=1024 \
        --verbose 2>&1 | grep -E "Building|Completed|Error|Warning|TRT"
    echo "det_10g engine tayyor: $DET_ENG"
else
    echo "[1/2] det_10g engine allaqachon bor — o'tkazildi"
fi

# ── w600k_r50 — ArcFace recognition ──────────────────────────────────────────
ARC_ONNX="$MODELS_DIR/buffalo_l/w600k_r50.onnx"
ARC_ENG_B1="$ENGINES_DIR/w600k_r50_b1_fp16.engine"
ARC_ENG_B16="$ENGINES_DIR/w600k_r50_b16_fp16.engine"

if [ ! -f "$ARC_ENG_B1" ]; then
    echo "[2/2] w600k_r50.onnx → TRT engine (FP16, batch=1..16, 112x112)..."
    trtexec \
        --onnx="$ARC_ONNX" \
        --saveEngine="$ARC_ENG_B16" \
        --fp16 \
        --minShapes="input.1:1x3x112x112" \
        --optShapes="input.1:8x3x112x112" \
        --maxShapes="input.1:16x3x112x112" \
        --workspace=512 2>&1 | grep -E "Building|Completed|Error|Warning|TRT"
    # batch=1 uchun alohida (agar batch=16 imkoni bo'lmasa)
    trtexec \
        --onnx="$ARC_ONNX" \
        --saveEngine="$ARC_ENG_B1" \
        --fp16 \
        --optShapes="input.1:1x3x112x112" \
        --minShapes="input.1:1x3x112x112" \
        --maxShapes="input.1:1x3x112x112" \
        --workspace=512 2>&1 | grep -E "Building|Completed|Error|Warning|TRT"
    echo "w600k_r50 engine tayyor: $ARC_ENG_B16"
else
    echo "[2/2] w600k_r50 engine allaqachon bor — o'tkazildi"
fi

echo ""
echo "=========================================="
echo " Tayyor enginelar:"
ls -lh "$ENGINES_DIR/"
echo "=========================================="
