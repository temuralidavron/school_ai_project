#!/bin/bash
# T1/T2 smoke test — spec: docs/superpowers/specs/2026-07-15-testlash-log-rejasi.md
# Ishlatish:
#   bash deepstream_v3/tests/smoke.sh          # T1: fayl rejimi (run_demo, 60s)
#   bash deepstream_v3/tests/smoke.sh --live   # T2: jonli kamera (cam16_2, 90s)
# Chiqish kodi: 0 = PASS, 1 = FAIL
set -u
cd "$(dirname "$0")/../.."

LIVE=0
[ "${1:-}" = "--live" ] && LIVE=1
FAIL=0
JLOG="logs/sightings-$(date +%F).jsonl"

say()  { echo "  $1"; }
pass() { echo "  PASS: $1"; }
fail() { echo "  FAIL: $1"; FAIL=1; }

echo "== smoke: oldindan tekshiruvlar =="
curl -sf --max-time 5 http://127.0.0.1:8000/monitoring/live/1/ >/dev/null \
  && pass "web javob beradi" || fail "web ishlamayapti (docker compose up -d web kafka kafka_consumer)"
[ "$FAIL" = "1" ] && exit 1

J0=$(wc -l < "$JLOG" 2>/dev/null || echo 0)

if [ "$LIVE" = "0" ]; then
  echo "== T1: fayl rejimi (run_demo, 60s) =="
  bash deepstream_v3/run_demo.sh >/dev/null 2>&1
  CONT=school_ai_ds3_run
else
  echo "== T2: jonli rejim (cam16_2, 90s) =="
  docker rm -f ds3_smoke >/dev/null 2>&1
  docker run -d --name ds3_smoke --gpus all --entrypoint python3 \
    --network school_ai_project_default \
    -v school_ai_project_insightface_models:/root/.insightface:ro \
    -v "$(pwd)/deepstream_v3/engines:/engines:ro" \
    -e KAFKA_BOOTSTRAP=kafka:9092 -e VIS_EVERY=0 \
    -e PGIE_CONFIG=/ds3/configs/pgie_det10g_1280.txt -e DET_INPUT_SZ=1280 \
    school_ai_ds3:latest /ds3/pipeline/main.py \
    --uri "999=https://edu-api.devel.uz/cam16_2" >/dev/null
  CONT=ds3_smoke
fi

# kadr oqimini kutish (jonli HLS ba'zan sekin ochiladi — 120s sabr)
OK=0
for i in $(seq 1 60); do
  docker logs "$CONT" 2>&1 | grep -q "frame#" && { OK=1; break; }
  docker ps --format '{{.Names}}' | grep -q "^$CONT$" || break
  sleep 2
done
if [ "$OK" = "1" ]; then
  pass "kadr oqimi boshlandi"
else
  fail "kadr oqimi boshlanmadi (120s) — oxirgi loglar:"
  docker logs --tail 8 "$CONT" 2>&1 | sed 's/^/    | /'
  docker rm -f "$CONT" >/dev/null 2>&1
  echo ""; echo "SMOKE: FAIL"; exit 1
fi

[ "$LIVE" = "0" ] && sleep 60 || sleep 90

# umumiy tekshiruvlar
docker logs "$CONT" 2>&1 | grep -q "Traceback" \
  && fail "pipeline logida Traceback bor" || pass "pipeline logi toza"

J1=$(wc -l < "$JLOG" 2>/dev/null || echo 0)
DJ=$((J1 - J0))

if [ "$LIVE" = "0" ]; then
  # T1: davomat va jurnal oqishi kerak
  ARR=$(curl -s http://127.0.0.1:8000/monitoring/live/1/api/ \
    | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('arrived_count',0))" 2>/dev/null || echo 0)
  [ "${ARR:-0}" -ge 5 ] && pass "davomat oqdi ($ARR bola)" || fail "davomat kam ($ARR < 5)"
  [ "$DJ" -ge 50 ] && pass "jurnal yozildi (+$DJ qator)" || fail "jurnal kam (+$DJ < 50)"
else
  # T2: bo'sh xonada accepted bo'lmasligi kerak; fps real-time atrofida
  ACC=$(python3 -c "
import json
n=0
for line in open('$JLOG'):
    d=json.loads(line)
    if d.get('cam')==999 and d.get('decision')=='accepted': n+=1
print(n)" 2>/dev/null || echo 0)
  [ "${ACC:-0}" = "0" ] && pass "bo'sh xonada 0 accepted" || fail "bo'sh xonada $ACC ta accepted — FP!"
  FPS=$(docker logs "$CONT" 2>&1 | grep frame# | tail -1 | grep -oE '[0-9]+ fps' | grep -oE '[0-9]+')
  if [ -n "${FPS:-}" ] && [ "$FPS" -ge 15 ] && [ "$FPS" -le 40 ]; then
    pass "fps real-time atrofida ($FPS)"
  else
    fail "fps chegaradan tashqari (${FPS:-topilmadi})"
  fi
  if docker exec "$CONT" sh -c 'test -f /tmp/ds3_health && test $(( $(date +%s) - $(stat -c %Y /tmp/ds3_health) )) -lt 30' 2>/dev/null; then
    pass "health fayl yangi"
  else
    fail "health fayl eski yoki mavjud emas"
  fi
fi

docker rm -f "$CONT" >/dev/null 2>&1

echo ""
[ "$FAIL" = "0" ] && echo "SMOKE: PASS" || echo "SMOKE: FAIL"
exit $FAIL
