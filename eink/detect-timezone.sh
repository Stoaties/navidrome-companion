#!/bin/bash
# Detect the system timezone from public-IP geolocation and apply it.
#
# Installed as a oneshot service (musiceink-tz.service) that runs at every boot,
# so the clock and the e-ink display self-correct — including if the device is
# moved to another network or region. Falls back gracefully and never fails the
# boot if detection doesn't work.
set -u
log() { echo "[tz-detect] $*"; }

tz=""
for url in \
  "http://ip-api.com/line?fields=timezone" \
  "https://ipapi.co/timezone" \
  "http://worldtimeapi.org/api/ip.txt"; do
  resp=$(curl -fsS --max-time 12 "$url" 2>/dev/null) || continue
  # Prefer an Area/City token (handles worldtimeapi's "timezone: X" lines too);
  # otherwise use the trimmed response (covers single-word zones like "UTC").
  cand=$(printf '%s\n' "$resp" | grep -oE '[A-Za-z_]+/[A-Za-z_]+(/[A-Za-z_]+)?' | head -1)
  [ -z "$cand" ] && cand=$(printf '%s' "$resp" | tr -d '[:space:]')
  if [ -n "$cand" ] && [ -f "/usr/share/zoneinfo/$cand" ]; then tz="$cand"; break; fi
done

if [ -z "$tz" ]; then
  log "could not detect a timezone; leaving it unchanged"
  exit 0
fi

cur=$(timedatectl show -p Timezone --value 2>/dev/null)
if [ "$tz" = "$cur" ]; then
  log "timezone already $tz"
  exit 0
fi
if timedatectl set-timezone "$tz"; then
  log "timezone set to $tz (was ${cur:-unknown})"
  # Nudge the display so its clock updates without waiting for a reboot.
  systemctl restart musiceink-display.service 2>/dev/null || true
else
  log "failed to set timezone to $tz"
fi
