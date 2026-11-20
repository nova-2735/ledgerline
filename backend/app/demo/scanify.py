"""Turn a digital invoice into a convincing scan: an image-only PDF with no text layer.

Pipeline: render page (PyMuPDF) → paper tone → stamps and handwriting → rotate → edge shadow →
sensor noise → blur → JPEG → single-image PDF. All randomness comes from
`random.Random(42 + index)`, so output is byte-identical across runs on the same machine.
"""

from __future__ import annotations

import io
import random
from functools import lru_cache
from pathlib import Path

import pymupdf
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from app.demo.invoice import Mark, ScanSpec

FontType = ImageFont.FreeTypeFont | ImageFont.ImageFont

_FONT_DIRS = (
    Path("C:/Windows/Fonts"),
    Path("/usr/share/fonts"),
    Path("/usr/local/share/fonts"),
    Path("/Library/Fonts"),
    Path("/System/Library/Fonts"),
)
HAND_FONTS = ("Inkfree.ttf", "segoepr.ttf", "LHANDW.TTF", "comic.ttf", "DejaVuSans-Oblique.ttf")
STAMP_FONTS = ("arialbd.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "Arial Bold.ttf")
INK = {
    "red": (196, 28, 44),
    "blue": (28, 52, 150),
    "black": (30, 30, 34),
    "green": (20, 110, 60),
}
PAPER = (247, 245, 239)
SCANNER_BED = (236, 236, 233)


@lru_cache
def _find_font_file(names: tuple[str, ...]) -> Path | None:
    for name in names:
        for d in _FONT_DIRS:
            if not d.is_dir():
                continue
            direct = d / name
            if direct.is_file():
                return direct
            found = (
                next(iter(sorted(d.rglob(name))), None) if d.parts[1:2] != ("Windows",) else None
            )
            if found:
                return found
    return None


def _font(names: tuple[str, ...], size: int) -> FontType:
    path = _find_font_file(names)
    if path is not None:
        return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size)


def _place(img: Image.Image, layer: Image.Image, center: tuple[float, float]) -> Image.Image:
    """Alpha-composite `layer` onto `img` centred at fractional page coords."""
    w, h = img.size
    x = int(center[0] * w - layer.width / 2)
    y = int(center[1] * h - layer.height / 2)
    base = img.convert("RGBA")
    full = Image.new("RGBA", base.size, (0, 0, 0, 0))
    full.paste(layer, (x, y), layer)
    return Image.alpha_composite(base, full).convert("RGB")


def _ink_texture(layer: Image.Image, rng: random.Random, density: float) -> Image.Image:
    """Knock small holes out of an ink layer so it looks pressed rather than printed."""
    alpha = layer.getchannel("A")
    holes = Image.new("L", layer.size, 255)
    d = ImageDraw.Draw(holes)
    n = int(layer.width * layer.height * density)
    for _ in range(n):
        cx, cy = rng.uniform(0, layer.width), rng.uniform(0, layer.height)
        r = rng.uniform(0.6, 2.2)
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=rng.randint(0, 150))
    layer.putalpha(ImageChops.multiply(alpha, holes))
    return layer


def _stamp(img: Image.Image, mark: Mark, rng: random.Random, scale: float) -> Image.Image:
    font = _font(STAMP_FONTS, int(15 * scale))
    color = INK.get(mark.color, INK["red"])
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    left, top, right, bottom = probe.textbbox((0, 0), mark.text, font=font)
    pad = int(9 * scale)
    w, h = int(right - left) + 2 * pad, int(bottom - top) + 2 * pad
    layer = Image.new("RGBA", (w + 8, h + 8), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    ink = (*color, 205)
    d.rounded_rectangle(
        (4, 4, w + 4, h + 4), radius=int(4 * scale), outline=ink, width=max(2, int(2.2 * scale))
    )
    inset = int(3 * scale)
    d.rounded_rectangle(
        (4 + inset, 4 + inset, w + 4 - inset, h + 4 - inset),
        radius=int(3 * scale),
        outline=ink,
        width=max(1, int(0.8 * scale)),
    )
    d.text((4 + pad - left, 4 + pad - top), mark.text, font=font, fill=ink)
    layer = _ink_texture(layer, rng, 0.0025)
    layer = layer.rotate(mark.angle, resample=Image.Resampling.BICUBIC, expand=True)
    return _place(img, layer, mark.at)


def _handwriting(img: Image.Image, mark: Mark, rng: random.Random, scale: float) -> Image.Image:
    font = _font(HAND_FONTS, int(19 * scale))
    color = INK.get(mark.color, INK["blue"])
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    # draw letter by letter with a wandering baseline and uneven pressure
    widths = [probe.textlength(ch, font=font) for ch in mark.text]
    height = int(34 * scale)
    layer = Image.new(
        "RGBA", (int(sum(widths) + 30 * scale), height + int(14 * scale)), (0, 0, 0, 0)
    )
    d = ImageDraw.Draw(layer)
    x = 6 * scale
    drift = 0.0
    for ch, cw in zip(mark.text, widths, strict=True):
        drift += rng.uniform(-0.6, 0.6) * scale
        alpha = rng.randint(185, 235)
        d.text((x, 4 * scale + drift), ch, font=font, fill=(*color, alpha))
        x += cw * rng.uniform(0.94, 1.04)
    # a quick underline stroke
    y0 = height - 2 * scale
    pts = [
        (6 * scale + i * (x - 6 * scale) / 8, y0 + rng.uniform(-1.5, 1.5) * scale) for i in range(9)
    ]
    d.line(pts, fill=(*color, 200), width=max(1, int(1.1 * scale)), joint="curve")
    layer = layer.filter(ImageFilter.GaussianBlur(0.35 * scale / 2))
    angle = mark.angle or rng.uniform(2.0, 5.0)
    layer = layer.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
    center = (mark.at[0] + layer.width / img.width / 2, mark.at[1])
    return _place(img, layer, center)


def _noise_tile(rng: random.Random, sigma: float, size: int = 256) -> Image.Image:
    data = bytes(
        max(0, min(255, int(round(128 + rng.gauss(0, sigma))))) for _ in range(size * size)
    )
    return Image.frombytes("L", (size, size), data)


def _add_noise(img: Image.Image, rng: random.Random, sigma: float) -> Image.Image:
    if sigma <= 0:
        return img
    tiles = [_noise_tile(rng, sigma) for _ in range(3)]
    size = tiles[0].width
    field = Image.new("L", img.size, 128)
    for ty in range(0, img.height, size):
        for tx in range(0, img.width, size):
            tile = tiles[rng.randrange(3)]
            if rng.random() < 0.5:
                tile = tile.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            if rng.random() < 0.5:
                tile = tile.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
            field.paste(tile, (tx, ty))
    noise = Image.merge("RGB", (field, field, field))
    return ImageChops.add(img, noise, scale=1.0, offset=-128)


def _shadow(img: Image.Image, side: str, rng: random.Random) -> Image.Image:
    if side not in {"left", "right"}:
        return img
    width = int(img.width * rng.uniform(0.045, 0.06))
    ramp = Image.linear_gradient("L").rotate(90, expand=True).resize((width, img.height))
    if side == "right":
        ramp = ramp.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    ramp = ramp.point(lambda v: 120 + v * 135 // 255)
    box = (
        (0, 0, width, img.height)
        if side == "left"
        else (img.width - width, 0, img.width, img.height)
    )
    region = ImageChops.multiply(img.crop(box), Image.merge("RGB", (ramp, ramp, ramp)))
    img.paste(region, box)
    return img


def scan_image(pdf_bytes: bytes, scan: ScanSpec, index: int) -> Image.Image:
    rng = random.Random(42 + index)
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        pix = doc[0].get_pixmap(dpi=scan.dpi, alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    scale = scan.dpi / 72
    img = ImageChops.multiply(img, Image.new("RGB", img.size, PAPER))
    img = ImageEnhance.Contrast(img).enhance(0.93)
    for mark in scan.stamps:
        img = _stamp(img, mark, rng, scale)
    for mark in scan.handwriting:
        img = _handwriting(img, mark, rng, scale)
    img = img.rotate(
        scan.rotate, resample=Image.Resampling.BICUBIC, expand=False, fillcolor=SCANNER_BED
    )
    img = _shadow(img, scan.shadow, rng)
    img = _add_noise(img, rng, scan.noise)
    if scan.blur > 0:
        img = img.filter(ImageFilter.GaussianBlur(scan.blur))
    return img


def image_pdf(img: Image.Image, quality: int, title: str) -> bytes:
    jpeg = io.BytesIO()
    img.save(jpeg, "JPEG", quality=quality, optimize=False, progressive=False)
    jpeg.seek(0)
    buf = io.BytesIO()
    c = Canvas(buf, pagesize=A4, invariant=1)
    c.setTitle(title)
    c.setCreator("Scan")
    c.drawImage(ImageReader(jpeg), 0, 0, width=A4[0], height=A4[1])
    c.showPage()
    c.save()
    return buf.getvalue()


def scanify(pdf_bytes: bytes, scan: ScanSpec, index: int, title: str = "Scanned document") -> bytes:
    return image_pdf(scan_image(pdf_bytes, scan, index), scan.jpeg_quality, title)
