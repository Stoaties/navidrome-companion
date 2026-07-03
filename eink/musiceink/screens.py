"""Draw the status and provisioning screens onto a 250x122 canvas."""
import time

from .panel import load_font
from .status import human_bytes


def _qr_image(data: str, box: int = 2, border: int = 2):
    import qrcode
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,
                       box_size=box, border=border)
    qr.add_data(data)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").convert("1")


def _fit_qr(data: str, target_px: int):
    """Render a QR and scale it (nearest-neighbour) to ~target_px square."""
    img = _qr_image(data, box=1, border=2)
    factor = max(1, target_px // img.size[0])
    if factor > 1:
        img = img.resize((img.size[0] * factor, img.size[1] * factor))
    return img


def render_status(panel, st: dict, web_port: int = 80):
    """Status screen: name, IP, disk free, track count, CPU/mem/temp + web QR."""
    img, d = panel.new_canvas()
    W, H = panel.width, panel.height
    f_title = load_font(20, bold=True)
    f = load_font(14)
    f_small = load_font(12)

    ip = st.get("ip") or "no network"
    port = "" if web_port == 80 else f":{web_port}"
    url = f"http://{ip}{port}/" if st.get("ip") else ""

    # --- web-UI QR on the right so a phone can open the interface in one scan ---
    qr_area = 0
    if url:
        qr = _fit_qr(url, target_px=86)
        qw, qh = qr.size
        qx = W - qw - 2
        qy = 16
        img.paste(qr, (qx, qy))
        d.text((qx + (qw - 46) // 2, qy + qh - 1), "scan me", font=f_small, fill=0)
        qr_area = qw + 6

    tx = 4
    right = W - qr_area
    d.text((tx, 0), "musicEink", font=f_title, fill=0)
    d.line((tx, 24, right, 24), fill=0)

    free = human_bytes(st["disk_free"])
    total = human_bytes(st["disk_total"])
    temp = st.get("temp")
    temp_s = f"  {temp:.0f}°C" if temp is not None else ""

    lines = [
        f"IP: {ip}",
        f"Free: {free} / {total}",
        f"Tracks: {st['tracks']}",
        f"CPU {st['cpu']}%  Mem {st['mem']}%{temp_s}",
    ]
    y = 30
    for ln in lines:
        d.text((tx, y), ln, font=f, fill=0)
        y += 18

    footer = time.strftime("updated %H:%M")
    downloading = st.get("downloading", 0)
    if downloading:
        footer += f"  ·  downloading {downloading}"
    elif url:
        footer += "  ·  scan for web UI"
    d.text((tx, H - 12), footer, font=f_small, fill=0)
    return img


def render_provisioning(panel, ap_ssid: str, ap_pass: str, portal_ip: str,
                        ap_active: bool):
    """Offline screen: QR to join the Pi's setup hotspot + instructions."""
    img, d = panel.new_canvas()
    W, H = panel.width, panel.height
    f_title = load_font(18, bold=True)
    f = load_font(13)
    f_small = load_font(11)

    d.text((4, 0), "Wi-Fi setup", font=f_title, fill=0)
    d.line((4, 22, W - 4, 22), fill=0)

    if ap_active:
        # WPA QR string: phones auto-join the hotspot when scanned.
        wifi_qr = f"WIFI:S:{ap_ssid};T:WPA;P:{ap_pass};;"
        qr = _fit_qr(wifi_qr, target_px=92)
        img.paste(qr, (4, 26))
        tx = 4 + qr.size[0] + 8
        steps = [
            "1. Scan to join",
            f"   “{ap_ssid}”",
            "2. Open in browser:",
            f"   http://{portal_ip}",
            "3. Pick your Wi-Fi",
            "   and enter password",
        ]
        y = 28
        for s in steps:
            d.text((tx, y), s, font=f, fill=0)
            y += 15
    else:
        d.text((4, 34), "Not connected to Wi-Fi.", font=f, fill=0)
        d.text((4, 52), "Setup hotspot is disabled.", font=f, fill=0)
        d.text((4, 74), "Enable provisioning in", font=f_small, fill=0)
        d.text((4, 88), "the config, or set Wi-Fi", font=f_small, fill=0)
        d.text((4, 102), "with a keyboard/console.", font=f_small, fill=0)
    return img


def render_message(panel, title: str, lines: list[str]):
    img, d = panel.new_canvas()
    W = panel.width
    d.text((4, 2), title, font=load_font(18, bold=True), fill=0)
    d.line((4, 24, W - 4, 24), fill=0)
    f = load_font(13)
    y = 32
    for ln in lines:
        d.text((4, y), ln, font=f, fill=0)
        y += 16
    d.text((4, panel.height - 12), time.strftime("%Y-%m-%d %H:%M"),
           font=load_font(11), fill=0)
    return img
