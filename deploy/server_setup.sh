#!/bin/bash
# =============================================================================
# 14-maktab SERVERINI TAYYORLASH — bir marta ishga tushiriladi.
#
#   sudo bash server_setup.sh
#
# Nima o'rnatadi:
#   1. NVIDIA drayver 595 + OPEN kernel modul   (RTX 5080 uchun open SHART)
#   2. Docker Engine + Compose plugin
#   3. nvidia-container-toolkit                 (GPU ni Docker ichida ishlatish)
#   4. git
#
# CUDA toolkit O'RNATILMAYDI — u kerak emas, CUDA konteyner image ichida keladi.
#
# Skript idempotent: bor narsani qayta o'rnatmaydi, xavfsiz qayta yurgizsa bo'ladi.
# =============================================================================
set -e

[ "$(id -u)" -eq 0 ] || { echo "XATO: sudo bilan ishga tushiring -> sudo bash $0"; exit 1; }

GREEN='\033[0;32m'; RED='\033[0;31m'; YEL='\033[0;33m'; NC='\033[0m'
ok()   { echo -e "  ${GREEN}OK${NC}   $1"; }
warn() { echo -e "  ${YEL}!${NC}    $1"; }
fail() { echo -e "  ${RED}XATO${NC} $1"; }

REBOOT_KERAK=0

echo "============================================================"
echo " 14-maktab AI davomat serveri — tayyorlash"
echo "============================================================"
echo

# ─── 0. Tekshiruvlar ─────────────────────────────────────────────────────────
echo "[0/5] Tizim tekshiruvi"
. /etc/os-release
echo "      OS     : $PRETTY_NAME"
echo "      kernel : $(uname -r)"
[ "${VERSION_ID:-}" = "24.04" ] || warn "Ubuntu 24.04 tavsiya qilinadi (hozir: ${VERSION_ID:-?})"

if lspci | grep -qi "NVIDIA"; then
  ok "NVIDIA videokarta topildi: $(lspci | grep -i 'VGA.*NVIDIA' | head -1 | cut -d: -f3- | xargs)"
else
  fail "NVIDIA videokarta topilmadi! Karta o'rnatilganini tekshiring."; exit 1
fi

BOSH=$(df -BG / | awk 'NR==2{gsub("G","",$4); print $4}')
if [ "${BOSH:-0}" -lt 100 ]; then
  warn "Diskda ${BOSH}G bo'sh joy — kamida 100G tavsiya qilinadi (image'lar 60G+)"
else
  ok "Disk: ${BOSH}G bo'sh"
fi
echo

# ─── 1. Asosiy paketlar ──────────────────────────────────────────────────────
echo "[1/5] Asosiy paketlar (git, curl, ca-certificates)"
apt-get update -qq
apt-get install -y -qq git curl ca-certificates gnupg >/dev/null
ok "git $(git --version | awk '{print $3}')"
echo

# ─── 2. NVIDIA drayver — OPEN modul ──────────────────────────────────────────
echo "[2/5] NVIDIA drayver (open kernel modul)"
if nvidia-smi >/dev/null 2>&1 && nvidia-smi -L 2>/dev/null | grep -qi nvidia; then
  ok "drayver ishlayapti: $(nvidia-smi --query-gpu=name,driver_version --format=csv,noheader | head -1)"
else
  echo "      drayver yo'q yoki ishlamayapti — o'rnatilmoqda..."
  apt-get install -y -qq nvidia-driver-595 "linux-modules-nvidia-595-open-$(uname -r)" >/dev/null 2>&1 || {
    warn "aniq versiya topilmadi, ubuntu-drivers bilan urinilmoqda"
    apt-get install -y -qq ubuntu-drivers-common >/dev/null
    ubuntu-drivers install --gpgpu 2>/dev/null || true
  }
  REBOOT_KERAK=1
  warn "drayver o'rnatildi — REBOOT kerak"
fi

# RTX 50xx (Blackwell) proprietary modulni QO'LLAB-QUVVATLAMAYDI.
# DKMS proprietary modul o'rnatilgan bo'lsa, u open modulni bosib ketadi.
if dpkg -l 2>/dev/null | grep -q "^ii  nvidia-dkms-"; then
  warn "nvidia-dkms paketi bor — u proprietary modul quradi va open modulni bosadi"
  echo "         RTX 5080 da bu 'nvidia-smi: No devices were found' beradi."
  echo "         Tuzatish:  sudo apt remove nvidia-dkms-595 && sudo apt install linux-modules-nvidia-595-open-\$(uname -r)"
fi
echo

# ─── 3. Docker ───────────────────────────────────────────────────────────────
echo "[3/5] Docker Engine + Compose"
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  ok "$(docker --version | cut -d, -f1)"
  ok "$(docker compose version | head -1)"
else
  echo "      o'rnatilmoqda (get.docker.com)..."
  curl -fsSL https://get.docker.com | sh >/dev/null 2>&1
  systemctl enable --now docker >/dev/null 2>&1
  ok "$(docker --version | cut -d, -f1)"
fi

# Oddiy foydalanuvchi sudo'siz docker ishlatishi uchun
REAL_USER="${SUDO_USER:-}"
if [ -n "$REAL_USER" ] && ! id -nG "$REAL_USER" | grep -qw docker; then
  usermod -aG docker "$REAL_USER"
  warn "$REAL_USER docker guruhiga qo'shildi — kuchga kirishi uchun qayta login qiling"
fi
echo

# ─── 4. nvidia-container-toolkit ─────────────────────────────────────────────
echo "[4/5] nvidia-container-toolkit (GPU ni Docker ichida ishlatish)"
if dpkg -l 2>/dev/null | grep -q "^ii  nvidia-container-toolkit"; then
  ok "o'rnatilgan: $(dpkg -l | awk '/^ii  nvidia-container-toolkit /{print $3}')"
else
  echo "      o'rnatilmoqda..."
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
    | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
  curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
    | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
    > /etc/apt/sources.list.d/nvidia-container-toolkit.list
  apt-get update -qq
  apt-get install -y -qq nvidia-container-toolkit >/dev/null
  ok "o'rnatildi"
fi

nvidia-ctk runtime configure --runtime=docker >/dev/null 2>&1
systemctl restart docker
ok "docker runtime sozlandi"
echo

# ─── 5. Yakuniy sinov ────────────────────────────────────────────────────────
echo "[5/5] YAKUNIY SINOV — GPU Docker ichida ko'rinadimi"
if [ "$REBOOT_KERAK" = "1" ]; then
  warn "drayver yangi o'rnatildi — avval REBOOT qiling, keyin shu skriptni qayta yurgizing"
  echo
  echo "      sudo reboot"
  exit 0
fi

if docker run --rm --gpus all nvidia/cuda:12.6.3-base-ubuntu24.04 nvidia-smi >/tmp/gputest.log 2>&1; then
  echo
  grep -E "NVIDIA-SMI|RTX|Driver Version" /tmp/gputest.log | head -2 | sed 's/^/      /'
  echo
  echo -e "  ${GREEN}============================================${NC}"
  echo -e "  ${GREEN} SERVER TAYYOR — GPU Docker ichida ishlayapti${NC}"
  echo -e "  ${GREEN}============================================${NC}"
  echo
  echo "  Keyingi qadam (loyihani ko'chirish):"
  echo "    git clone git@github.com:temuralidavron/school_ai_project.git"
  echo "    cd school_ai_project && cat deploy/DEPLOY_14_MAKTAB.md"
else
  echo
  fail "GPU Docker ichida KO'RINMADI. Xato:"
  tail -5 /tmp/gputest.log | sed 's/^/      /'
  echo
  echo "  Tekshiring:"
  echo "    nvidia-smi                                # hostda ishlaydimi"
  echo "    dmesg | grep -i nvrm | tail -5            # 'open kernel modules' deyilsa -> nvidia-dkms ni oling"
  echo "    dpkg -l | grep nvidia-container-toolkit   # o'rnatilganmi"
  exit 1
fi
