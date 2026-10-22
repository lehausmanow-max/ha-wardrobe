"""The picture of today's look for the phone: up to four garment thumbnails on one square JPEG,
written to Home Assistant's media folder."""

import logging
import re
import shutil
from datetime import date, timedelta

from PIL import Image, ImageDraw, ImageFont, ImageOps

from . import config

log = logging.getLogger("wardrobe.collage")
SIDE = 1080
TILE = SIDE // 2
PAD = 24
BACKGROUND = (236, 235, 232)
NAME = re.compile(r"^look-.+-(\d{4}-\d{2}-\d{2})-\d+\.jpg$")
TODAY = re.compile(r"^today-(.+)\.jpg$")
UPPER = ("top", "knitwear", "outerwear")
LOWER = ("bottom", "dress")


def pick_tiles(items: list[dict], limit: int = 4) -> list[dict]:
    """Top, knitwear or outerwear first, then bottom or dress, then shoes. The upper group gives
    way when there are more than four, so bottom and shoes keep their place."""
    shown = [g for g in items if g.get("photo")]
    upper = [g for g in shown if g["category"] in UPPER]
    lower = [g for g in shown if g["category"] in LOWER]
    shoes = [g for g in shown if g["category"] == "shoes"]
    rest = lower[:2] + shoes[:1]
    upper = upper[:max(1, limit - len(rest))]
    return (upper + rest)[:limit]


def _cells(n: int) -> list[tuple[int, int]]:
    """Top-left corners in a 2×2 grid; a lone last tile is centred on its row."""
    if n <= 1:
        return [(TILE // 2, TILE // 2)]
    cells = [(0, 0), (TILE, 0), (0, TILE), (TILE, TILE)][:n]
    if n == 3:
        cells[2] = (TILE // 2, TILE)
    return cells


def make(items: list[dict], filename: str) -> bool:
    """Write the collage unless it exists already. Returns whether a file is there."""
    target = config.HA_MEDIA_DIR / filename
    if target.exists():
        return True
    tiles = pick_tiles(items)
    if not tiles:
        return False
    canvas = Image.new("RGB", (SIDE, SIDE), BACKGROUND)
    for (x, y), g in zip(_cells(len(tiles)), tiles):
        src = config.THUMB_DIR / g["photo"]
        try:
            with Image.open(src) as im:
                tile = ImageOps.contain(im.convert("RGB"), (TILE - 2 * PAD, TILE - 2 * PAD))
        except OSError as exc:
            log.warning("Collage: can't read %s: %s", src.name, exc)
            continue
        canvas.paste(tile, (x + (TILE - tile.width) // 2, y + (TILE - tile.height) // 2))
    config.HA_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    canvas.save(tmp, "JPEG", quality=85, optimize=True)
    tmp.replace(target)
    return True


def cleanup(today: date, keep_days: int = 2) -> int:
    """Delete collages more than keep_days old. Returns how many went."""
    folder = config.HA_MEDIA_DIR
    if not folder.is_dir():
        return 0
    cut = today - timedelta(days=keep_days)
    gone = 0
    for f in folder.glob("look-*.jpg"):
        m = NAME.match(f.name)
        try:
            if m and date.fromisoformat(m.group(1)) < cut:
                f.unlink()
                gone += 1
        except (ValueError, OSError):
            continue
    return gone


def today_name(slug: str) -> str:
    return f"today-{slug}.jpg"


def set_today(slug: str, look_filename: str | None) -> None:
    """Make today-<slug>.jpg the current look: a copy of its collage, or a plain picture saying
    there's no look. A dashboard card can always show the same file."""
    folder = config.HA_MEDIA_DIR
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / today_name(slug)
    tmp = target.with_suffix(".tmp")
    if look_filename and (folder / look_filename).exists():
        shutil.copyfile(folder / look_filename, tmp)
    else:
        canvas = Image.new("RGB", (SIDE, SIDE), BACKGROUND)
        draw = ImageDraw.Draw(canvas)
        try:
            font = ImageFont.load_default(size=64)
        except TypeError:  # older Pillow without sizes
            font = ImageFont.load_default()
        text = "No look today"
        box = draw.textbbox((0, 0), text, font=font)
        draw.text(((SIDE - (box[2] - box[0])) // 2, (SIDE - (box[3] - box[1])) // 2), text,
                  fill=(120, 118, 112), font=font)
        canvas.save(tmp, "JPEG", quality=85)
    tmp.replace(target)


def remove_stale_today(slugs: set[str]) -> int:
    """Delete today-<slug>.jpg files of people who aren't there any more (or were renamed)."""
    folder = config.HA_MEDIA_DIR
    if not folder.is_dir():
        return 0
    gone = 0
    for f in folder.glob("today-*.jpg"):
        m = TODAY.match(f.name)
        if m and m.group(1) not in slugs:
            try:
                f.unlink()
                gone += 1
            except OSError:
                continue
    return gone
