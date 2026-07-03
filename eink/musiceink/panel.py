"""Thin wrapper around the Waveshare 2.13" e-Paper driver.

Loads the driver named by EINK_DRIVER from EINK_LIB (where install.sh places the
Waveshare ``waveshare_epd`` package) and offers a couple of high-level render
helpers so the rest of the app never touches the low-level API.
"""
import importlib
import os
import sys

from PIL import Image, ImageDraw, ImageFont

EINK_LIB = os.environ.get("EINK_LIB", "/opt/musiceink/lib")
EINK_DRIVER = os.environ.get("EINK_DRIVER", "epd2in13_V4")

_FONT_DIRS = [
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/truetype/liberation",
]


def load_font(size: int, bold: bool = False):
    names = (["DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"] if bold
             else ["DejaVuSans.ttf", "LiberationSans-Regular.ttf"])
    for d in _FONT_DIRS:
        for n in names:
            p = os.path.join(d, n)
            if os.path.exists(p):
                return ImageFont.truetype(p, size)
    return ImageFont.load_default()


class Panel:
    """Wraps a Waveshare EPD. width/height are the landscape dimensions."""

    def __init__(self):
        if EINK_LIB not in sys.path:
            sys.path.insert(0, EINK_LIB)
        mod = importlib.import_module("waveshare_epd." + EINK_DRIVER)
        self.epd = mod.EPD()
        # Landscape: the panel is physically 122x250 (portrait); we draw 250x122.
        self.width = self.epd.height
        self.height = self.epd.width
        self._initialized = False

    def _ensure_init(self):
        if not self._initialized:
            self.epd.init()
            self.epd.Clear(0xFF)
            self._initialized = True

    def new_canvas(self) -> tuple[Image.Image, ImageDraw.ImageDraw]:
        img = Image.new("1", (self.width, self.height), 255)
        return img, ImageDraw.Draw(img)

    def show(self, img: Image.Image):
        self._ensure_init()
        self.epd.display(self.epd.getbuffer(img))

    def sleep(self):
        try:
            self.epd.sleep()
        except Exception:
            pass
