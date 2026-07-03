"""Wi-Fi onboarding: a captive portal to receive the home Wi-Fi credentials.

Flow (when the AP path is enabled): the Pi has no network, so it brings up its
own hotspot; the e-ink shows a QR to join it and the portal URL. The user joins,
opens the portal, picks their network and enters the password, and we write it to
wpa_supplicant and reconnect.

SAFETY: bringing up the hotspot means dropping the current Wi-Fi association, so
AP activation is OFF by default (config ``enable_ap``). The credential-apply and
portal logic below work independently and are safe to run; only ``start_ap`` /
``stop_ap`` touch the live connection.
"""
import http.server
import os
import re
import socket
import subprocess
import threading
import urllib.parse

WPA_CONF = os.environ.get("WPA_CONF", "/etc/wpa_supplicant/wpa_supplicant.conf")


def scan_networks(iface: str) -> list[str]:
    """Return nearby SSIDs (best-effort)."""
    ssids: list[str] = []
    try:
        subprocess.run(["wpa_cli", "-i", iface, "scan"], timeout=8,
                       capture_output=True)
        out = subprocess.check_output(["wpa_cli", "-i", iface, "scan_results"],
                                      text=True, timeout=8)
        for line in out.splitlines()[1:]:
            cols = line.split("\t")
            if len(cols) >= 5 and cols[4] and cols[4] not in ssids:
                ssids.append(cols[4])
    except (subprocess.SubprocessError, OSError):
        pass
    return ssids


def apply_wifi(iface: str, ssid: str, psk: str) -> bool:
    """Add/replace the network in wpa_supplicant and reconnect. Returns ok."""
    block = 'network={\n\tssid="%s"\n%s\n}\n' % (
        _esc(ssid),
        ('\tkey_mgmt=NONE' if not psk else '\tpsk="%s"' % _esc(psk)),
    )
    try:
        existing = ""
        if os.path.exists(WPA_CONF):
            with open(WPA_CONF) as fh:
                existing = fh.read()
        # Drop any prior block for this SSID, then append the new one.
        existing = _strip_network(existing, ssid)
        if "ctrl_interface" not in existing:
            existing = ("ctrl_interface=DIR=/var/run/wpa_supplicant "
                        "GROUP=netdev\nupdate_config=1\n" + existing)
        with open(WPA_CONF, "w") as fh:
            fh.write(existing.rstrip() + "\n\n" + block)
        os.chmod(WPA_CONF, 0o600)
        subprocess.run(["wpa_cli", "-i", iface, "reconfigure"], timeout=10,
                       capture_output=True)
        return True
    except OSError:
        return False


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _strip_network(conf: str, ssid: str) -> str:
    pattern = re.compile(r'network=\{[^}]*ssid="%s"[^}]*\}\s*' % re.escape(ssid))
    return pattern.sub("", conf)


class _PortalHandler(http.server.BaseHTTPRequestHandler):
    iface = "wlan0"
    on_submit = None  # set by run_portal

    def _html(self, body: str, code: int = 200):
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode())

    def do_GET(self):
        nets = scan_networks(self.iface)
        opts = "".join(f'<option value="{n}">{n}</option>' for n in nets)
        self._html(f"""<!doctype html><meta name=viewport
content="width=device-width,initial-scale=1"><title>musicEink Wi-Fi</title>
<style>body{{font-family:sans-serif;max-width:420px;margin:2rem auto;padding:1rem}}
input,select,button{{width:100%;padding:.6rem;margin:.4rem 0;font-size:1rem}}</style>
<h2>Connect musicEink to Wi-Fi</h2>
<form method=post>
<label>Network</label><select name=ssid>{opts}<option value="">— other —</option></select>
<label>Or type SSID</label><input name=ssid_manual placeholder="network name">
<label>Password</label><input name=psk type=password>
<button>Connect</button></form>""")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        form = urllib.parse.parse_qs(self.rfile.read(length).decode())
        ssid = (form.get("ssid_manual", [""])[0] or form.get("ssid", [""])[0]).strip()
        psk = form.get("psk", [""])[0]
        ok = bool(ssid) and self.on_submit and self.on_submit(ssid, psk)
        self._html("<h2>%s</h2><p>%s</p>" % (
            ("Connecting…" if ok else "Failed"),
            ("musicEink is joining “%s”. This page will disconnect; reconnect to "
             "your normal Wi-Fi and find the player by its IP." % ssid if ok
             else "Could not save the network. Try again.")))

    def log_message(self, *_):
        pass


def run_portal(iface: str, ip: str = "0.0.0.0", port: int = 80,
               on_submit=None) -> threading.Thread:
    """Start the captive portal in a background thread. Returns the thread."""
    _PortalHandler.iface = iface
    _PortalHandler.on_submit = staticmethod(on_submit) if on_submit else None
    httpd = http.server.ThreadingHTTPServer((ip, port), _PortalHandler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return t


# --- Hotspot control (OFF by default; requires hostapd + dnsmasq installed) ----
def hotspot_available() -> bool:
    return all(_which(b) for b in ("hostapd", "dnsmasq"))


def _which(binary: str) -> bool:
    return subprocess.run(["sh", "-c", f"command -v {binary}"],
                          capture_output=True).returncode == 0


def start_ap(iface: str, ssid: str, passphrase: str, ip: str) -> bool:
    """Bring up an AP hotspot. DANGER: drops the current Wi-Fi connection.

    Only called when enable_ap is set AND the Pi is already offline, so there is
    no live connection to lose. Requires hostapd + dnsmasq.
    """
    if not hotspot_available():
        return False
    hostapd_conf = "/tmp/musiceink_hostapd.conf"
    dnsmasq_conf = "/tmp/musiceink_dnsmasq.conf"
    with open(hostapd_conf, "w") as fh:
        fh.write(f"interface={iface}\nssid={ssid}\nhw_mode=g\nchannel=6\n"
                 f"wpa=2\nwpa_passphrase={passphrase}\nwpa_key_mgmt=WPA-PSK\n"
                 f"rsn_pairwise=CCMP\nauth_algs=1\n")
    with open(dnsmasq_conf, "w") as fh:
        net = ip.rsplit(".", 1)[0]
        fh.write(f"interface={iface}\nbind-interfaces\n"
                 f"dhcp-range={net}.10,{net}.100,255.255.255.0,12h\n"
                 f"address=/#/{ip}\n")  # captive: resolve everything to us
    try:
        subprocess.run(["ip", "addr", "flush", "dev", iface], check=False)
        subprocess.run(["ip", "addr", "add", f"{ip}/24", "dev", iface], check=True)
        subprocess.run(["ip", "link", "set", iface, "up"], check=True)
        subprocess.Popen(["dnsmasq", "-C", dnsmasq_conf, "-d"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.Popen(["hostapd", hostapd_conf],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except (subprocess.SubprocessError, OSError):
        return False


def stop_ap(iface: str):
    for proc in ("hostapd", "dnsmasq"):
        subprocess.run(["pkill", "-f", proc], capture_output=True)
    subprocess.run(["ip", "addr", "flush", "dev", iface], check=False)
