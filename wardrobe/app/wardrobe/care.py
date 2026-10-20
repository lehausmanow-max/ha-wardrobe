"""Care defaults by fibre, wash-due tracking and the laundry sorter."""

import re

from . import colors

# Most delicate first: in a blend, the most delicate fibre sets the rules.
MATERIAL_CARE = [
    ("leather", {"wash": "no_wash", "temp": None, "cycle": "normal", "dry": "line",
                 "iron": "no", "dry_clean": "any", "notes": "Specialist clean only; condition twice a year",
                 "wash_after": 0}),
    ("suede", {"wash": "no_wash", "temp": None, "cycle": "normal", "dry": "line",
               "iron": "no", "dry_clean": "any", "notes": "Brush dry; protect with spray", "wash_after": 0}),
    ("silk", {"wash": "hand", "temp": 30, "cycle": "delicate", "dry": "line",
              "iron": "low", "dry_clean": "P", "notes": "Mild detergent, no wringing", "wash_after": 3}),
    ("cashmere", {"wash": "hand", "temp": 30, "cycle": "wool", "dry": "flat",
                  "iron": "low", "dry_clean": "P", "notes": "Dry flat; store folded, never hung",
                  "wash_after": 6}),
    ("wool", {"wash": "machine", "temp": 30, "cycle": "wool", "dry": "flat",
              "iron": "low", "dry_clean": "P", "notes": "Wool programme; air between wears",
              "wash_after": 6}),
    ("merino", {"wash": "machine", "temp": 30, "cycle": "wool", "dry": "flat",
                "iron": "low", "dry_clean": "P", "notes": "Wool programme", "wash_after": 5}),
    ("down", {"wash": "machine", "temp": 30, "cycle": "delicate", "dry": "tumble_low",
              "iron": "no", "dry_clean": "no", "notes": "Tumble low with dryer balls to re-loft",
              "wash_after": 0}),
    ("viscose", {"wash": "hand", "temp": 30, "cycle": "delicate", "dry": "line",
                 "iron": "low", "dry_clean": "P", "notes": "Shrinks when hot", "wash_after": 2}),
    ("rayon", {"wash": "hand", "temp": 30, "cycle": "delicate", "dry": "line",
               "iron": "low", "dry_clean": "P", "notes": "Shrinks when hot", "wash_after": 2}),
    ("linen", {"wash": "machine", "temp": 40, "cycle": "normal",
               "dry": "line", "iron": "high", "dry_clean": "any", "notes": "Iron while damp",
               "wash_after": 2}),
    ("denim", {"wash": "machine", "temp": 30, "cycle": "normal", "dry": "line",
               "iron": "medium", "dry_clean": "any", "notes": "Inside out, cold, rarely",
               "wash_after": 10}),
    ("elastane", {"wash": "machine", "temp": 30, "cycle": "delicate", "dry": "line",
                  "iron": "low", "dry_clean": "no", "notes": "Heat kills stretch", "wash_after": 2}),
    ("polyester", {"wash": "machine", "temp": 40, "cycle": "normal",
                   "dry": "tumble_low", "iron": "low", "dry_clean": "P", "notes": "", "wash_after": 2}),
    ("nylon", {"wash": "machine", "temp": 30, "cycle": "normal", "dry": "line",
               "iron": "low", "dry_clean": "P", "notes": "", "wash_after": 2}),
    ("cotton", {"wash": "machine", "temp": 40, "cycle": "normal",
                "dry": "tumble_low", "iron": "high", "dry_clean": "any",
                "notes": "Darks at 30 °C to keep colour", "wash_after": 2}),
]

GENERIC = {"wash": "machine", "temp": 30, "cycle": "normal", "dry": "line",
           "iron": "low", "dry_clean": "any", "notes": "", "wash_after": 2}

# Sensible wear counts between washes, by category, when the fibre doesn't decide it.
CATEGORY_WASH_AFTER = {"top": 1, "knitwear": 5, "bottom": 4, "dress": 2,
                       "outerwear": 0, "shoes": 0, "accessory": 0}


def label_bleach(new: dict, old: dict) -> dict:
    """Bleach is recorded only from a care label, never chosen by hand or set by defaults.

    The edit form has no bleach field, so a bleach value read from the label is carried over
    from the stored care (`old`) and anything else sent in `new` is dropped.
    """
    out = {k: v for k, v in new.items() if k not in ("bleach", "bleach_from_label")}
    if old.get("bleach") and old.get("bleach_from_label"):
        out["bleach"] = old["bleach"]
        out["bleach_from_label"] = True
    return out


def defaults_for(material: str, category: str = "") -> dict:
    m = (material or "").lower()
    for fibre, care in MATERIAL_CARE:
        if re.search(rf"\b{fibre}", m):
            out = dict(care)
            break
    else:
        out = dict(GENERIC)
    if out["wash"] == "no_wash":
        out["wash_after"] = 0
    elif category in CATEGORY_WASH_AFTER:
        base = CATEGORY_WASH_AFTER[category]
        # Wool and denim earn extra wears; outerwear, shoes and accessories aren't tracked.
        hardy = re.search(r"\b(wool|merino|cashmere|denim)", m)
        out["wash_after"] = 0 if base == 0 else (max(base, out["wash_after"]) if hardy else base)
    return out


def colour_group(garment: dict) -> str:
    main = (garment.get("colors") or [None])[0]
    if not main:
        return "colours"
    _, light, sat = colors.hls(main)
    if light > 0.82 and sat < 0.35:
        return "whites"
    if light < 0.3:
        return "darks"
    if light > 0.68:
        return "lights"
    return "colours"


def wash_key(garment: dict) -> tuple:
    care = garment.get("care") or {}
    wash = care.get("wash") or "machine"
    if wash in ("dry_clean", "no_wash", "spot"):
        return (wash, None, None)
    temp = care.get("temp") or 30
    cycle = care.get("cycle") or "normal"
    # Hand-wash items can share a machine wool/hand programme.
    if wash == "hand":
        cycle = "wool"
    return ("machine" if wash == "machine" else "hand", temp, cycle)


LOAD_LABEL = {
    "dry_clean": "Dry cleaner", "no_wash": "Specialist / spot clean", "spot": "Spot clean",
}


def sort_laundry(garments: list[dict]) -> list[dict]:
    """Group laundry into loads. Items wash at the lowest temperature of their group."""
    buckets: dict[tuple, list[dict]] = {}
    for g in garments:
        wk = wash_key(g)
        group = colour_group(g) if wk[0] in ("machine", "hand") else "-"
        # Whites may go with lights; darks stay apart.
        if group == "lights":
            group = "whites & lights"
        if group == "whites":
            group = "whites & lights"
        buckets.setdefault((wk[0], wk[2], group), []).append(g)

    loads = []
    for (method, cycle, group), items in buckets.items():
        temps = [wash_key(i)[1] for i in items if wash_key(i)[1]]
        temp = min(temps) if temps else None
        if method in LOAD_LABEL:
            title = LOAD_LABEL[method]
        else:
            prog = {"normal": "normal", "delicate": "delicate", "wool": "wool / hand"}[cycle]
            title = f"{group.capitalize()}, {temp} °C, {prog} programme"
        loads.append({"title": title, "method": method, "temp": temp, "cycle": cycle,
                      "group": group, "items": items})
    order = {"machine": 0, "hand": 1, "spot": 2, "dry_clean": 3, "no_wash": 4}
    loads.sort(key=lambda l: (order.get(l["method"], 9), l["group"], -(l["temp"] or 0)))
    return loads
