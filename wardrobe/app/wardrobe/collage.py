"""The picture of today's look for the phone: up to four garment thumbnails on one square JPEG,
written to Home Assistant's media folder."""

import logging
import re
from datetime import date, timedelta

from PIL import Image, ImageOps

from . import config

log = logging.getLogger("wardrobe.collage")
SIDE = 1080
TILE = SIDE // 2
PAD = 24
BACKGROUND = (236, 235, 232)
NAME = re.compile(r"^look-.+-(\d{4}-\d{2}-\d{2})-\d+\.jpg$")
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
