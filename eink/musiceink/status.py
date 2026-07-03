"""Collect the stats shown on the e-ink status screen.

Everything here is best-effort and dependency-light: psutil is used when
available, with /proc fallbacks, so the display keeps working on a minimal
DietPi install.
"""
import os
import shutil
import socket
import subprocess
import time

AUDIO_EXTS = {".mp3", ".flac", ".m4a", ".ogg", ".opus", ".wav", ".aac",
              ".wma", ".alac", ".aiff"}


def local_ip(iface: str = "") -> str:
    """Best local IPv4. Prefers the given interface, else the default route."""
    if iface:
        ip = _iface_ip(iface)
        if ip:
            return ip
    # Fall back to the address used to reach the default gateway.
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))  # no packets actually sent
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return ""


def _iface_ip(iface: str) -> str:
    try:
        out = subprocess.check_output(
            ["ip", "-4", "-o", "addr", "show", iface], text=True, timeout=5)
        for tok in out.split():
            if tok.count(".") == 3 and "/" in tok:
                return tok.split("/")[0]
    except (subprocess.SubprocessError, OSError):
        pass
    return ""


def has_default_route() -> bool:
    try:
        out = subprocess.check_output(["ip", "route"], text=True, timeout=5)
        return "default via" in out
    except (subprocess.SubprocessError, OSError):
        return False


def is_connected(iface: str = "") -> bool:
    """We consider the Pi 'connected' once it has a LAN IP and a route."""
    return bool(local_ip(iface)) and has_default_route()


def disk_free(path: str) -> tuple[int, int]:
    """(free_bytes, total_bytes) for the filesystem holding ``path``."""
    target = path if os.path.exists(path) else "/"
    usage = shutil.disk_usage(target)
    return usage.free, usage.total


def count_tracks(music_dir: str) -> int:
    if not music_dir or not os.path.isdir(music_dir):
        return 0
    n = 0
    for _root, _dirs, files in os.walk(music_dir):
        for f in files:
            if os.path.splitext(f)[1].lower() in AUDIO_EXTS:
                n += 1
    return n


def cpu_percent(sample: float = 0.4) -> int:
    try:
        import psutil
        return int(round(psutil.cpu_percent(interval=sample)))
    except Exception:
        return _cpu_percent_proc(sample)


def _cpu_percent_proc(sample: float) -> int:
    try:
        a = _read_cpu_times()
        time.sleep(sample)
        b = _read_cpu_times()
        idle = b[3] - a[3]
        total = sum(b) - sum(a)
        return int(round(100 * (total - idle) / total)) if total else 0
    except Exception:
        return 0


def _read_cpu_times():
    with open("/proc/stat") as fh:
        parts = fh.readline().split()[1:8]
    return [int(x) for x in parts]


def mem_percent() -> int:
    try:
        import psutil
        return int(round(psutil.virtual_memory().percent))
    except Exception:
        pass
    try:
        info = {}
        with open("/proc/meminfo") as fh:
            for line in fh:
                k, v = line.split(":")
                info[k] = int(v.split()[0])
        total = info["MemTotal"]
        avail = info.get("MemAvailable", info["MemFree"])
        return int(round(100 * (total - avail) / total)) if total else 0
    except Exception:
        return 0


def cpu_temp_c() -> float | None:
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as fh:
            return int(fh.read().strip()) / 1000.0
    except Exception:
        return None


def human_bytes(n: int) -> str:
    for unit in ("B", "K", "M", "G", "T"):
        if n < 1024 or unit == "T":
            return f"{n:.0f}{unit}" if unit in ("B", "K") else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}T"


def gather(music_dir: str, iface: str = "") -> dict:
    free, total = disk_free(music_dir)
    return {
        "ip": local_ip(iface),
        "connected": is_connected(iface),
        "disk_free": free,
        "disk_total": total,
        "tracks": count_tracks(music_dir),
        "cpu": cpu_percent(),
        "mem": mem_percent(),
        "temp": cpu_temp_c(),
    }
