# musicEink — e-ink display for the Pi music server

Drives a **Waveshare 2.13" e-Paper HAT (250×122)** to make the headless Pi
self-explanatory:

- **Online** → a status screen with the local **IP**, **free disk space**,
  **track count**, **CPU / memory / temperature**, and a **QR code that opens
  the web interface** on your phone.
- **Offline** → a Wi-Fi onboarding screen: a QR to join the Pi's setup hotspot
  and the URL of a small captive portal where you enter your home Wi-Fi.

```
 online:                              offline:
 ┌──────────────────────────┐        ┌──────────────────────────┐
 │ musicEink        ▓▓▓ QR   │        │ Wi-Fi setup              │
 │ ─────────────    ▓▓▓ web  │        │ ▓▓▓▓  1. Scan to join    │
 │ IP: 10.0.0.60            │        │ ▓▓▓▓     "musicEink-setup"│
 │ Free: 48.2G / 57G        │        │ ▓▓▓▓  2. Open 192.168.4.1 │
 │ Tracks: 128              │        │ ▓▓▓▓  3. Pick your Wi-Fi  │
 │ CPU 12% Mem 41% 47°C     │        │                          │
 └──────────────────────────┘        └──────────────────────────┘
```

## Install (on the Pi)

```bash
cd navidrome-companion/eink
sudo ./install.sh              # or: sudo ./install.sh epd2in13_V3
sudo reboot                    # only needed the first time, to enable SPI
sudo systemctl start musiceink-display
```

The installer also sets up **`musiceink-tz.service`**, which detects the
timezone from the server's public-IP geolocation at every boot and applies it
with `timedatectl` — so the displayed clock is correct without manual config,
even if the Pi moves networks. (Run `/opt/musiceink/detect-timezone.sh` to force
it.)

Wiring: seat the HAT on the 40-pin header. The panel version (V2/V3/V4) sets the
driver — pass it to `install.sh`; if the screen stays blank, try another. Preview
a single frame without the service:

```bash
set -a; . /etc/musiceink.env; set +a
python3 -m musiceink.display --once
```

## Configuration — `/etc/musiceink.env`

| Variable | Default | Meaning |
| --- | --- | --- |
| `EINK_DRIVER` | `epd2in13_V4` | Waveshare driver module (`_V3`, `_V2`) |
| `MUSIC_DIR` | `/mnt/dietpi_userdata/Music` | Counted for the track total & free space |
| `WIFI_IFACE` | `wlan0` | Interface used for IP / connectivity |
| `WEB_PORT` | `80` | Port put in the web-UI QR code |
| `REFRESH_ACTIVE_SECONDS` | `60` | Refresh interval while a download runs |
| `REFRESH_IDLE_SECONDS` | `180` | Refresh interval when idle |
| `ACTIVITY_URL` | `http://127.0.0.1/api/activity` | Companion endpoint polled for download activity |
| `PROVISION_ENABLE_AP` | `0` | **Off by default** — see safety note |
| `AP_SSID` / `AP_PASS` | `musicEink-setup` / `musicsetup` | Setup hotspot |
| `PORTAL_IP` | `192.168.4.1` | Captive-portal address |

### Wi-Fi onboarding & the safety switch

Bringing up the setup hotspot **drops the Pi's current Wi-Fi** (it can only be
an AP *or* a client, not both). So `PROVISION_ENABLE_AP` is **`0`** by default:
the offline screen still appears, but the Pi won't self-isolate. Enable it only
when you can reach the Pi over a keyboard/HDMI or Ethernet if something goes
wrong. The hotspot path also needs `hostapd` and `dnsmasq` installed.

The credential capture (captive portal → `wpa_supplicant`) is independent of the
AP and safe on its own.

## Layout

```
eink/
  musiceink/
    status.py        # gather IP / disk / tracks / CPU / mem / temp
    panel.py         # Waveshare driver wrapper + fonts
    screens.py       # draw the status & onboarding screens (+ QR codes)
    provisioning.py  # captive portal, wpa_supplicant apply, hotspot (gated)
    display.py       # daemon loop (online→status, offline→onboarding)
  systemd/musiceink-display.service
  install.sh
```
