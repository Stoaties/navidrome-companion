#!/bin/bash
# Install the musicEink e-ink display service on a Raspberry Pi (DietPi /
# Raspberry Pi OS). Run as root:  sudo ./install.sh [driver]
# driver defaults to epd2in13_V4 (try epd2in13_V3 / epd2in13_V2 if the panel
# stays blank).
set -euo pipefail

DRIVER="${1:-epd2in13_V4}"
DEST=/opt/musiceink
LIB="$DEST/lib"
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "== installing apt dependencies =="
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  python3 python3-pil python3-numpy python3-spidev python3-lgpio \
  python3-gpiozero python3-psutil python3-qrcode fonts-dejavu-core curl

echo "== enabling SPI =="
CONF=/boot/firmware/config.txt; [ -f "$CONF" ] || CONF=/boot/config.txt
if ! grep -q "^dtparam=spi=on" "$CONF"; then
  echo "dtparam=spi=on" >> "$CONF"
  echo "   SPI enabled in $CONF (a reboot is required for it to take effect)"
fi

echo "== installing app to $DEST =="
mkdir -p "$LIB/waveshare_epd"
cp -r "$HERE/musiceink" "$DEST/"

echo "== fetching Waveshare e-Paper driver ($DRIVER) =="
BASE="https://raw.githubusercontent.com/waveshareteam/e-Paper/master/RaspberryPi_JetsonNano/python/lib/waveshare_epd"
for f in __init__.py epdconfig.py "$DRIVER.py"; do
  curl -fsSL "$BASE/$f" -o "$LIB/waveshare_epd/$f"
done

echo "== writing /etc/musiceink.env =="
if [ ! -f /etc/musiceink.env ]; then
  cat > /etc/musiceink.env <<ENV
PYTHONPATH=$DEST
EINK_LIB=$LIB
EINK_DRIVER=$DRIVER
MUSIC_DIR=/mnt/dietpi_userdata/Music
WIFI_IFACE=wlan0
WEB_PORT=80
# Refresh fast while downloading, slow when idle.
REFRESH_ACTIVE_SECONDS=60
REFRESH_IDLE_SECONDS=180
ACTIVITY_URL=http://127.0.0.1/api/activity
# Wi-Fi onboarding hotspot. OFF by default: turning it on drops the current
# Wi-Fi to broadcast a setup AP, so only enable it with console access.
PROVISION_ENABLE_AP=0
AP_SSID=musicEink-setup
AP_PASS=musicsetup
PORTAL_IP=192.168.4.1
ENV
fi

echo "== installing systemd service =="
cp "$HERE/systemd/musiceink-display.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable musiceink-display.service

echo
echo "Done. If SPI was just enabled, reboot first:  reboot"
echo "Then start it:  systemctl start musiceink-display"
echo "Test one frame: python3 -m musiceink.display --once  (with env from /etc/musiceink.env)"
