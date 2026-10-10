"""Pictures: a fingerprint to find the same picture from another site, size, thumbnails.

The fingerprint is a difference hash: the picture shrunk to 9x8 grey pixels,
one bit per pair of neighbours. Recompressing or rescaling a picture -- what
every site does to an upload -- changes a few bits at most; a different
picture changes about half of them.
"""
import logging

from PIL import Image, ImageOps

log = logging.getLogger(__name__)
SIMILAR = 5        # bits two fingerprints may differ in and still be one picture


def info(path):
    """(fingerprint, width, height) of a picture; (None, None, None) for anything else."""
    try:
        with Image.open(path) as img:
            width, height = img.size
            img.draft("L", (64, 64))            # JPEG: decode small, much faster
            return _dhash(img), width, height
    except Exception:                          # video, audio, a format Pillow lacks
        return None, None, None


def _dhash(img):
    small = img.convert("L").resize((9, 8), Image.LANCZOS)
    px = list(small.getdata())
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | (px[row * 9 + col] > px[row * 9 + col + 1])
    return "%016x" % bits


def distance(a, b):
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def thumbnail(src, dst, size=200):
    with Image.open(src) as img:
        img = ImageOps.exif_transpose(img)
        img.thumbnail((size, size))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        dst.parent.mkdir(parents=True, exist_ok=True)
        img.save(dst, "JPEG", quality=82)


def avatar(src, dst, size=128):
    """A square profile picture: the middle of the source, scaled to size."""
    with Image.open(src) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        img = ImageOps.fit(img, (size, size), Image.LANCZOS)
        dst.parent.mkdir(parents=True, exist_ok=True)
        img.save(dst, "JPEG", quality=88)
