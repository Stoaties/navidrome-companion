"""musicEink display daemon.

Online  -> status screen (IP, disk free, track count, CPU/mem/temp + web-UI QR).
Offline -> Wi-Fi onboarding screen (QR to join the setup hotspot + portal URL).

Run as a service (see systemd/musiceink-display.service) or directly:
    python3 -m musiceink.display
Use ``--once`` to render a single frame and exit (handy for testing).
"""
import os
import sys
import time

from . import screens, status
from .panel import Panel


def _env(name, default):
    return os.environ.get(name, default)


class Config:
    music_dir = _env("MUSIC_DIR", "/mnt/dietpi_userdata/Music")
    iface = _env("WIFI_IFACE", "wlan0")
    web_port = int(_env("WEB_PORT", "80"))
    refresh = int(_env("REFRESH_SECONDS", "60"))
    offline_poll = int(_env("OFFLINE_POLL_SECONDS", "15"))
    enable_ap = _env("PROVISION_ENABLE_AP", "0") == "1"
    ap_ssid = _env("AP_SSID", "musicEink-setup")
    ap_pass = _env("AP_PASS", "musicsetup")
    portal_ip = _env("PORTAL_IP", "192.168.4.1")
    # Force a full (de-ghosting) refresh at least this often, even if unchanged.
    full_refresh_every = int(_env("FULL_REFRESH_EVERY", "20"))


def _status_signature(st: dict) -> tuple:
    # Bucket volatile values so the panel doesn't flash on every 1% CPU wiggle.
    return (
        st["ip"], st["tracks"], st["disk_free"] >> 27,  # ~128MB buckets
        round(st["cpu"], -1), round(st["mem"], -1),
        int(st["temp"]) if st["temp"] is not None else -1,
    )


class Daemon:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.panel = Panel()
        self._ap_started = False
        self._portal = None
        self._last_sig = None
        self._iters = 0

    def _maybe_show(self, img, sig):
        force = (self._iters % self.cfg.full_refresh_every == 0)
        if sig != self._last_sig or force:
            self.panel.show(img)
            self._last_sig = sig
        self._iters += 1

    def _start_provisioning(self):
        from . import provisioning
        if not (self.cfg.enable_ap and provisioning.hotspot_available()):
            return False
        if not self._ap_started:
            ok = provisioning.start_ap(self.cfg.iface, self.cfg.ap_ssid,
                                       self.cfg.ap_pass, self.cfg.portal_ip)
            if ok:
                def _apply(ssid, psk):
                    provisioning.stop_ap(self.cfg.iface)
                    return provisioning.apply_wifi(self.cfg.iface, ssid, psk)
                self._portal = provisioning.run_portal(
                    self.cfg.iface, self.cfg.portal_ip, 80, _apply)
                self._ap_started = True
        return self._ap_started

    def _stop_provisioning(self):
        if self._ap_started:
            from . import provisioning
            provisioning.stop_ap(self.cfg.iface)
            self._ap_started = False

    def tick(self) -> int:
        """Render one frame. Returns how long to sleep before the next."""
        if status.is_connected(self.cfg.iface):
            self._stop_provisioning()
            st = status.gather(self.cfg.music_dir, self.cfg.iface)
            img = screens.render_status(self.panel, st, self.cfg.web_port)
            self._maybe_show(img, _status_signature(st))
            return self.cfg.refresh
        ap_active = self._start_provisioning()
        img = screens.render_provisioning(self.panel, self.cfg.ap_ssid,
                                          self.cfg.ap_pass, self.cfg.portal_ip,
                                          ap_active)
        self._maybe_show(img, ("provision", ap_active))
        return self.cfg.offline_poll

    def run(self):
        try:
            while True:
                delay = self.tick()
                time.sleep(delay)
        except KeyboardInterrupt:
            pass
        finally:
            self.panel.sleep()


def main():
    cfg = Config()
    daemon = Daemon(cfg)
    if "--once" in sys.argv:
        daemon.tick()
        daemon.panel.sleep()
        return
    daemon.run()


if __name__ == "__main__":
    main()
