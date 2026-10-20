"""Colour maths: hex parsing, Lab distance, fashion colour names, neutrals and harmony."""

import colorsys
import math

# A working vocabulary of garment colours. Names are what people say about clothes.
NAMED = {
    "black": "#161616", "charcoal": "#3a3b3e", "grey": "#8a8b8d", "light grey": "#c4c5c7",
    "white": "#f6f6f3", "ivory": "#efe9da", "beige": "#d6c6a5", "sand": "#c9b48d",
    "camel": "#b0844f", "khaki": "#a49a6a", "tan": "#b98d5e", "brown": "#6a4630",
    "chocolate": "#3f2a1f", "navy": "#1f2a44", "denim": "#4a6587", "light blue": "#a9c4e0",
    "blue": "#2f5bb7", "cobalt": "#1f47c4", "teal": "#1e7277", "turquoise": "#3fb8b0",
    "olive": "#5d6136", "green": "#2f7a43", "forest": "#22412d", "sage": "#9fb099",
    "mint": "#bfe3cf", "burgundy": "#6a1f2b", "red": "#c0262d", "rust": "#a5482a",
    "orange": "#e0782a", "terracotta": "#c0643f", "mustard": "#c99a2e", "yellow": "#f0d03c",
    "pink": "#e79ab4", "blush": "#ecc6c0", "fuchsia": "#c42a83", "purple": "#5d3a8a",
    "lavender": "#b8a7d9", "plum": "#5a2a4a", "silver": "#b9bcc0", "gold": "#c6a24a",
}

# Colours that behave like neutrals in an outfit even though they have a hue.
HONORARY_NEUTRALS = {"navy", "denim", "beige", "sand", "camel", "khaki", "tan", "brown",
                     "chocolate", "ivory", "olive", "charcoal", "light blue"}


def parse_hex(value: str) -> tuple[int, int, int] | None:
    if not isinstance(value, str):
        return None
    v = value.strip().lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    if len(v) != 6:
        return None
    try:
        return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)
    except ValueError:
        return None


def to_hex(rgb) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(max(0, min(255, int(c))) for c in rgb))


def normalize_hex(value: str) -> str | None:
    """Accept '#abc', 'abcdef' or a colour name; return '#rrggbb'."""
    if isinstance(value, str) and value.strip().lower() in NAMED:
        return NAMED[value.strip().lower()]
    rgb = parse_hex(value)
    return to_hex(rgb) if rgb else None


def _lin(c: float) -> float:
    c /= 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def rgb_to_lab(rgb) -> tuple[float, float, float]:
    r, g, b = (_lin(c) for c in rgb)
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t):
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def delta_e(hex_a: str, hex_b: str) -> float:
    a, b = parse_hex(hex_a), parse_hex(hex_b)
    if not a or not b:
        return 999.0
    la, lb = rgb_to_lab(a), rgb_to_lab(b)
    return math.dist(la, lb)


_NAMED_LAB = {name: rgb_to_lab(parse_hex(h)) for name, h in NAMED.items()}


def name_of(hex_value: str) -> str:
    rgb = parse_hex(hex_value)
    if not rgb:
        return "unknown"
    lab = rgb_to_lab(rgb)
    return min(_NAMED_LAB, key=lambda n: math.dist(lab, _NAMED_LAB[n]))


def hls(hex_value: str) -> tuple[float, float, float]:
    rgb = parse_hex(hex_value) or (128, 128, 128)
    h, l, s = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
    return h * 360, l, s


def is_neutral(hex_value: str) -> bool:
    h, l, s = hls(hex_value)
    if l < 0.14 or l > 0.92 or s < 0.14:
        return True
    return name_of(hex_value) in HONORARY_NEUTRALS


def hue_gap(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return min(d, 360 - d)


def harmony(hexes: list[str]) -> tuple[int, str]:
    """Score 0-100 for a set of garment main colours, with a short reason."""
    hexes = [h for h in hexes if parse_hex(h)]
    if not hexes:
        return 70, "No colour data yet"
    accents = [h for h in hexes if not is_neutral(h)]
    # Collapse accents that are basically the same colour.
    distinct: list[str] = []
    for h in accents:
        if all(delta_e(h, d) > 18 for d in distinct):
            distinct.append(h)

    lights = [hls(h)[1] for h in hexes]
    contrast = max(lights) - min(lights)

    if not distinct:
        if contrast < 0.12 and len(hexes) > 2:
            return 80, "Tonal neutrals; add texture to keep it from going flat"
        return 90, "All neutrals, safe and easy"
    if len(distinct) == 1:
        return 96, f"Neutral base with one {name_of(distinct[0])} accent"
    if len(distinct) == 2:
        gap = hue_gap(hls(distinct[0])[0], hls(distinct[1])[0])
        a, b = name_of(distinct[0]), name_of(distinct[1])
        if gap <= 35:
            return 88, f"Analogous {a} and {b}"
        if 150 <= gap <= 210:
            return 82, f"Complementary {a} and {b}, bold but deliberate"
        if 100 <= gap < 150:
            return 66, f"{a.capitalize()} and {b} are a loud pairing"
        return 52, f"{a.capitalize()} and {b} compete with each other"
    return max(25, 60 - 12 * (len(distinct) - 2)), f"{len(distinct)} accent colours, too many"
