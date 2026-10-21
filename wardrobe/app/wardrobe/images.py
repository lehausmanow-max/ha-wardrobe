"""Photo handling: normalise uploads, strip metadata, build thumbnails, read dominant colours."""

import base64
import io
import uuid

from PIL import Image, ImageOps

from . import colors, config

MAX_SIDE = 2048
THUMB_SIDE = 480
AI_SIDE = 1024
# Reading labels: fibre percentages are unreadable at AI_SIDE.
READ_SIDE = 1568
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


class ImageError(ValueError):
    pass


def _open(data: bytes) -> Image.Image:
    if len(data) > MAX_UPLOAD_BYTES:
        raise ImageError("Photo is larger than 20 MB")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as exc:  # Pillow raises a zoo of types
        raise ImageError("That file isn't a photo this app can read (use JPEG, PNG or WebP)") from exc
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            bg.paste(img, mask=img.split()[-1])
            img = bg
        else:
            img = img.convert("RGB")
    return img.convert("RGB")


def save_upload(data: bytes) -> tuple[str, Image.Image]:
    """Store a resized, metadata-free JPEG plus thumbnail. Returns (filename, image)."""
    img = _open(data)
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    name = f"{uuid.uuid4().hex}.jpg"
    # Saving a fresh JPEG drops EXIF, including any GPS position from the phone.
    img.save(config.MEDIA_DIR / name, "JPEG", quality=88, optimize=True)
    thumb = img.copy()
    thumb.thumbnail((THUMB_SIDE, THUMB_SIDE))
    thumb.save(config.THUMB_DIR / name, "JPEG", quality=82, optimize=True)
    return name, img


def delete_files(filename: str) -> None:
    for folder in (config.MEDIA_DIR, config.THUMB_DIR):
        try:
            (folder / filename).unlink()
        except FileNotFoundError:
            pass


def for_ai(filename: str, side: int = AI_SIDE) -> tuple[str, str]:
    """Return (media_type, base64) of a downscaled copy for vision models."""
    img = Image.open(config.MEDIA_DIR / filename).convert("RGB")
    img.thumbnail((side, side))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return "image/jpeg", base64.b64encode(buf.getvalue()).decode()


def colors_of(filename: str) -> list[str]:
    """dominant_colors of a stored photo."""
    with Image.open(config.MEDIA_DIR / filename) as img:
        return dominant_colors(img.convert("RGB"))


def dominant_colors(img: Image.Image, count: int = 3) -> list[str]:
    """Estimate garment colours: ignore the backdrop (sampled from the border), keep big clusters."""
    small = img.copy()
    small.thumbnail((160, 160))
    w, h = small.size
    px = small.load()

    border = [px[x, 0] for x in range(w)] + [px[x, h - 1] for x in range(w)]
    border += [px[0, y] for y in range(h)] + [px[w - 1, y] for y in range(h)]
    bg = tuple(sorted(c[i] for c in border)[len(border) // 2] for i in range(3))
    bg_hex = colors.to_hex(bg)

    # Focus on the central area where the garment usually sits.
    box = (int(w * 0.15), int(h * 0.12), int(w * 0.85), int(h * 0.92))
    centre = small.crop(box)
    quant = centre.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
    palette = quant.getpalette() or []
    found = []
    for freq, idx in sorted(quant.getcolors() or [], reverse=True):
        rgb = tuple(palette[idx * 3: idx * 3 + 3])
        hx = colors.to_hex(rgb)
        if colors.delta_e(hx, bg_hex) < 12:
            continue
        if any(colors.delta_e(hx, f) < 14 for f, _ in found):
            continue
        found.append((hx, freq))
    total = sum(f for _, f in found) or 1
    result = [hx for hx, f in found if f / total > 0.08][:count]
    return result or [bg_hex]
