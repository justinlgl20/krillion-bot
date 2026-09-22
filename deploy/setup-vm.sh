#!/usr/bin/env bash
# Runs ON the VM (deploy.sh calls it over ssh). Idempotent.
# Installs python + venv, deps, the systemd unit, then (re)starts the bot.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/krillion-bot}"
SERVICE=krillion-bot
RUN_USER="$(id -un)"

cd "$APP_DIR"

# The 1 GB Always Free micro shape has little or no swap (Oracle Linux ships
# ~1 GB, Ubuntu none); dnf/apt metadata + pip can OOM it hard enough that even
# ssh stops answering. Make sure there is at least 2 GB of swap first.
# fallocate is instant; no dd fallback, as writing 2 GB of zeros through the
# page cache on a slow boot volume is itself enough to make the box unreachable.
SWAP_KB=$(awk '/^SwapTotal/ {print $2}' /proc/meminfo)
if [ "$SWAP_KB" -lt $((2 * 1024 * 1024)) ] && ! swapon --show=NAME --noheadings | grep -qx /swapfile; then
    echo "==> Adding 2G swapfile"
    if [ -f /swapfile ] || sudo fallocate -l 2G /swapfile 2>/dev/null; then
        sudo chmod 600 /swapfile
        sudo mkswap /swapfile >/dev/null
        sudo swapon /swapfile
        grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
    else
        echo "!!  fallocate failed; continuing without extra swap"
    fi
fi

# Every heavy step below runs through this: lowest CPU priority, and (where
# systemd is present) inside a scope capped well under the VM's RAM so the OOM
# killer takes the installer, never sshd or the kernel.
as_root() {
    if command -v systemd-run >/dev/null 2>&1; then
        sudo systemd-run --quiet --scope \
            -p MemoryMax=600M -p MemorySwapMax=1G -p CPUWeight=10 -- nice -n 19 "$@"
    else
        sudo nice -n 19 "$@"
    fi
}
capped() { as_root sudo -u "$RUN_USER" env "PATH=$PATH" "$@"; }

# Oracle Linux refreshes dnf metadata for every enabled repo hourly; that alone
# can push a 1 GB box into swap-thrash. dnf still refreshes on demand when used.
if systemctl list-unit-files dnf-makecache.timer >/dev/null 2>&1 \
    && systemctl is-enabled --quiet dnf-makecache.timer 2>/dev/null; then
    echo "==> Disabling dnf-makecache.timer"
    sudo systemctl disable --now dnf-makecache.timer >/dev/null 2>&1
fi

echo "==> Installing system packages"
if command -v apt-get >/dev/null 2>&1; then
    # Ubuntu / Debian (Canonical Ubuntu images on Oracle Cloud)
    PY=python3
    if ! "$PY" -m venv --help >/dev/null 2>&1 || ! "$PY" -m pip --version >/dev/null 2>&1; then
        as_root env DEBIAN_FRONTEND=noninteractive apt-get update -qq
        as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends \
            python3 python3-venv python3-pip >/dev/null
    fi
elif command -v dnf >/dev/null 2>&1; then
    # Oracle Linux 8/9 - system python is too old, use 3.11
    PY=python3.11
    if ! command -v "$PY" >/dev/null 2>&1; then
        # Only the two repos that carry python; the default set (UEK, ksplice, oci_included, ...)
        # pulls hundreds of MB of metadata into RAM on every run.
        OL="$(. /etc/os-release && echo "${VERSION_ID%%.*}")"
        as_root dnf install -y -q --nodocs --setopt=install_weak_deps=False \
            --disablerepo='*' --enablerepo="ol${OL}_baseos_latest,ol${OL}_appstream" \
            python3.11 python3.11-pip >/dev/null
    fi
else
    echo "Unsupported distro: need apt-get or dnf" >&2
    exit 1
fi

echo "==> Creating virtualenv + installing"
if [ ! -x .venv/bin/python ]; then
    "$PY" -m venv .venv
fi
# Build in-venv rather than in pip's isolated build env, which would download
# setuptools on every deploy. After the first run this step needs no network.
if ! .venv/bin/python -c 'import setuptools, wheel; assert int(setuptools.__version__.split(".")[0]) >= 68' >/dev/null 2>&1; then
    capped .venv/bin/pip install --quiet --no-cache-dir 'setuptools>=68' wheel
fi
# --only-binary: never compile aiohttp/Pillow/numpy/matplotlib from source; a
# C build is what pins a 1 GB VM at 100% CPU and swaps it into the ground. If
# no wheel exists for this Python, fail loudly instead.
capped .venv/bin/pip install --quiet --no-cache-dir --no-build-isolation --only-binary=:all: . \
    || { echo "!!  No prebuilt wheels for $(.venv/bin/python --version); install a Python with wheel support" >&2; exit 1; }
mkdir -p data

# Leaderboard images: DejaVu Sans for text (usually preinstalled) and Noto Color
# Emoji for the result rows (~10 MB, fetched once). Without it the bot sends text.
if [ ! -f fonts/NotoColorEmoji.ttf ]; then
    echo "==> Downloading Noto Color Emoji font"
    mkdir -p fonts
    curl -fsSL -o fonts/NotoColorEmoji.ttf \
        https://github.com/googlefonts/noto-emoji/raw/v2.047/fonts/NotoColorEmoji.ttf \
        || echo "!!  Font download failed; leaderboards will be text-only until it exists"
fi
if ! ls /usr/share/fonts/*/DejaVuSans.ttf /usr/share/fonts/*/*/DejaVuSans.ttf >/dev/null 2>&1; then
    echo "==> Installing DejaVu Sans"
    if command -v apt-get >/dev/null 2>&1; then
        as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends \
            fonts-dejavu-core >/dev/null
    else
        OL="$(. /etc/os-release && echo "${VERSION_ID%%.*}")"
        as_root dnf install -y -q --nodocs --setopt=install_weak_deps=False \
            --disablerepo='*' --enablerepo="ol${OL}_baseos_latest,ol${OL}_appstream" \
            dejavu-sans-fonts >/dev/null
    fi
fi

if [ ! -f .env ]; then
    cp .env.example .env
    echo
    echo "!!  $APP_DIR/.env was created from .env.example."
    echo "!!  Set DISCORD_TOKEN in it, then run:  sudo systemctl restart $SERVICE"
    echo
fi
chmod 600 .env

if command -v getenforce >/dev/null 2>&1 && [ "$(getenforce)" != "Disabled" ]; then
    # systemd may only read service inputs labelled for the system (usr_t) and
    # only execute binaries labelled bin_t. -h: never relabel symlink targets
    # (.venv/bin/python3.x points at the system interpreter).
    echo "==> Applying SELinux labels"
    sudo chcon -R -h -t usr_t "$APP_DIR"
    sudo chcon -R -h -t bin_t "$APP_DIR/.venv/bin"
fi

echo "==> Installing systemd unit"
sed -e "s|__APP_DIR__|$APP_DIR|g" -e "s|__USER__|$RUN_USER|g" \
    deploy/krillion-bot.service | sudo tee /etc/systemd/system/$SERVICE.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable $SERVICE >/dev/null 2>&1

if grep -qE '^DISCORD_TOKEN=.+' .env; then
    echo "==> Restarting $SERVICE"
    sudo systemctl restart $SERVICE
    sleep 3
    sudo systemctl --no-pager --lines=15 status $SERVICE || true
else
    echo "==> DISCORD_TOKEN not set; service enabled but not started."
fi
