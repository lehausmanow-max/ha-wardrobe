"""The AI jobs, each with a prompt and strict validation of what comes back."""

import json

from .. import colors, taxonomy
from .providers import AIError, parse_json

SYSTEM = (
    "You are a precise wardrobe assistant for a couple who manage their clothes in a private "
    "home app. Be concrete and practical. Comment on garments and how they fit, never on "
    "anyone's body. Use metric units and EU sizes."
)


def _clamp(v, lo, hi, default):
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def _pick(v, allowed, default):
    v = str(v or "").strip().lower()
    return v if v in allowed else default


def _list(v, allowed):
    if isinstance(v, str):
        v = [v]
    return [x for x in (str(i).strip().lower() for i in (v or [])) if x in allowed]


# ---------------------------------------------------------------- shared validation

_MISSING = object()


def _garment_fields(data: dict, partial: bool = False) -> dict:
    """Garment fields as seen on photos. partial=True leaves out what the model didn't give,
    so a re-read never proposes a made-up default; otherwise missing fields get defaults."""
    out = {}
    raw = {k: data.get(k, _MISSING) for k in ("name", "category", "subcategory", "colors", "pattern",
                                               "material", "formality", "warmth", "seasons", "occasions")}
    have = {k: v is not _MISSING and v not in (None, "", []) for k, v in raw.items()}
    category = _pick(data.get("category"), taxonomy.CATEGORIES, None)
    if category or not partial:
        out["category"] = category or "top"
    cat = out.get("category") or "top"
    if have["name"] or not partial:
        out["name"] = str(data.get("name") or "").strip()[:60]
    sub = _pick(data.get("subcategory"), taxonomy.CATEGORIES[cat]["sub"], "")
    if sub or not partial:
        out["subcategory"] = sub
    hexes = [h for h in (colors.normalize_hex(c) for c in (data.get("colors") or [])) if h][:3]
    if hexes or not partial:
        out["colors"] = hexes
    pattern = _pick(data.get("pattern"), taxonomy.PATTERNS, None)
    if pattern or not partial:
        out["pattern"] = pattern or "solid"
    material = str(data.get("material") or "").strip().lower()[:60]
    if material or not partial:
        out["material"] = material
    for k in ("formality", "warmth"):
        v = _clamp(data.get(k), 1, 5, None)
        if v is not None or not partial:
            out[k] = 3 if v is None else v
    for k, allowed in (("seasons", taxonomy.SEASONS), ("occasions", taxonomy.OCCASIONS)):
        v = _list(data.get(k), allowed)
        if v or not partial:
            out[k] = v
    return out


def _care_fields(data: dict) -> dict:
    """Care as read from a label. bleach is None when the label has no bleach symbol."""
    f = taxonomy.CARE_FIELDS
    temp = data.get("temp")
    try:
        temp = int(temp) if temp is not None else None
    except (TypeError, ValueError):
        temp = None
    if temp is not None:
        temp = min(f["temp"], key=lambda t: abs(t - temp))
    care = {
        "wash": _pick(data.get("wash"), f["wash"], "machine"),
        "temp": temp,
        "cycle": _pick(data.get("cycle"), f["cycle"], "normal"),
        "bleach": _pick(data.get("bleach"), f["bleach"], None),
        "dry": _pick(data.get("dry"), f["dry"], "line"),
        "iron": _pick(data.get("iron"), f["iron"], "medium"),
        "dry_clean": _pick(data.get("dry_clean"), [x.lower() for x in f["dry_clean"]], "any"),
        "notes": str(data.get("notes") or "")[:200],
    }
    if care["dry_clean"] in ("p", "f"):
        care["dry_clean"] = care["dry_clean"].upper()
    return care


def _confidence(v):
    return _pick(v, ["high", "medium", "low"], "medium")


def _care_prompt(indent: str = "") -> str:
    f = taxonomy.CARE_FIELDS
    lines = [
        f'"wash": one of {f["wash"]}  (tub = machine, hand in tub = hand, crossed tub = no_wash)',
        f'"temp": maximum wash temperature in °C, one of {f["temp"]} or null (dots: 1=30, 2=40, 3=50/60)',
        f'"cycle": one of {f["cycle"]} (one bar under tub = delicate, two bars = wool/very gentle)',
        f'"bleach": one of {f["bleach"]}, or null if the label has no bleach symbol',
        f'"dry": one of {f["dry"]} (square with circle = tumble; dots = heat; crossed = no_tumble; square with line = line/flat)',
        f'"iron": one of {f["iron"]} (dots: 1=low, 2=medium, 3=high)',
        f'"dry_clean": one of {f["dry_clean"]}',
        '"notes": any extra text instructions, e.g. "wash inside out" ("" if none)',
    ]
    return "\n".join(f"{indent}- {x}" for x in lines)


# ---------------------------------------------------------------- tagging

def tag_garment(provider, image) -> dict:
    cats = {k: v["sub"] for k, v in taxonomy.CATEGORIES.items()}
    prompt = f"""Look at this garment photo and describe the garment for a wardrobe database.
Return JSON with these keys:
- "name": short descriptive name, max 5 words (e.g. "Navy merino crewneck")
- "category": one of {list(cats)}
- "subcategory": one of the subcategories for that category: {json.dumps(cats)}
- "colors": up to 3 main colours of the garment itself (not the background) as hex strings, most dominant first
- "pattern": one of {taxonomy.PATTERNS}
- "material": best guess of fabric, e.g. "cotton", "wool", "denim", "linen", "polyester", "leather"
- "formality": 1 (lounge) to 5 (formal)
- "warmth": 1 (very light, summer) to 5 (very warm, winter)
- "seasons": subset of {taxonomy.SEASONS}
- "occasions": subset of {taxonomy.OCCASIONS}
- "brand": brand if a logo or label is clearly visible, else ""
"""
    data = parse_json(provider.ask(prompt, images=[image], want_json=True, system=SYSTEM))
    out = _garment_fields(data)
    out["brand"] = str(data.get("brand") or "").strip()[:40]
    return out


# ---------------------------------------------------------------- care label

def read_care_label(provider, image) -> dict:
    prompt = f"""This is a photo of a garment's care label (ISO/GINETEX laundry symbols and/or text).
Read it and return JSON with:
- "composition": fibre composition as written, e.g. "80% wool, 20% polyamide" ("" if not visible)
{_care_prompt()}
- "confidence": "high", "medium" or "low"
"""
    data = parse_json(provider.ask(prompt, images=[image], want_json=True, system=SYSTEM))
    return {"care": _care_fields(data), "composition": str(data.get("composition") or "")[:120],
            "confidence": _confidence(data.get("confidence"))}


# ---------------------------------------------------------------- all photos of one garment

PHOTO_ROLES = ["front", "back", "detail", "care_label", "brand_tag", "other"]
CARE_KEYS = ("wash", "temp", "cycle", "bleach", "dry", "iron", "dry_clean")


def read_garment(provider, images: list, hints: dict | None = None) -> dict:
    """Read every photo of one garment in a single call: the garment, its care label, its tags.

    hints maps a 1-based photo number to what the owner said the photo is.
    Returns roles (one per image, in order), garment fields (only those the model gave),
    logo_brand, labels {brand, size_label, composition, care or None} and confidence.
    """
    n = len(images)
    cats = {k: v["sub"] for k, v in taxonomy.CATEGORIES.items()}
    hint_text = "".join(f"\nPhoto {i} is a {what} (the owner said so)." for i, what in sorted((hints or {}).items()))
    prompt = f"""These {n} photos, numbered 1 to {n} in the order given, all show ONE garment: the garment
itself (front, back, details) and possibly its care label and its brand or size tag.{hint_text}

Return JSON with these keys:
- "photos": {n} objects in photo order, each {{"photo": <number>, "role": one of {PHOTO_ROLES}}}.
  care_label = a sewn-in label with washing symbols and/or fibre composition.
  brand_tag = a neck or waist tag with the brand and/or size.
- "garment": what the photos of the garment itself show:
  - "name": short descriptive name, max 5 words (e.g. "Navy merino crewneck")
  - "category": one of {list(cats)}
  - "subcategory": one of the subcategories for that category: {json.dumps(cats)}
  - "colors": up to 3 main colours of the garment (not the background) as hex strings, most dominant first
  - "pattern": one of {taxonomy.PATTERNS}
  - "material": best guess of the fabric from how it looks, e.g. "cotton", "wool", "denim"
  - "formality": 1 (lounge) to 5 (formal)
  - "warmth": 1 (very light, summer) to 5 (very warm, winter)
  - "seasons": subset of {taxonomy.SEASONS}
  - "occasions": subset of {taxonomy.OCCASIONS}
  - "logo_brand": the brand only if a logo is visible on the garment itself, else ""
- "labels": what the care label and tags say ({{}} if there are none):
  - "brand": the brand printed on a tag or label, else ""
  - "size_label": the size exactly as printed, e.g. "M", "EU 40", "W32 L32", else ""
  - "composition": fibre composition with percentages and English fibre names, e.g.
    "80% wool, 20% polyamide". Labels repeat it in several languages: give it once. If shell and
    lining differ, give the shell first, then "lining: ...". "" if not visible.
  - "care": null if no care symbols are visible. Otherwise an object with these keys (a care label
    may be photographed on both sides; combine them):
{_care_prompt("    ")}
- "confidence": {{"garment": "high"|"medium"|"low", "labels": "high"|"medium"|"low"}}
"""
    data = parse_json(provider.ask(prompt, images=images, want_json=True, system=SYSTEM,
                                   max_tokens=3000, timeout=150))
    roles = ["other"] * n
    for pos, p in enumerate(data.get("photos") or []):
        if not isinstance(p, dict):
            continue
        try:
            i = int(p.get("photo", pos + 1)) - 1
        except (TypeError, ValueError):
            i = pos
        if 0 <= i < n:
            roles[i] = _pick(p.get("role"), PHOTO_ROLES, "other")
    garment_raw = data.get("garment") if isinstance(data.get("garment"), dict) else {}
    labels_raw = data.get("labels") if isinstance(data.get("labels"), dict) else {}
    care_raw = labels_raw.get("care")
    care = None
    if isinstance(care_raw, dict) and any(care_raw.get(k) not in (None, "") for k in CARE_KEYS):
        care = _care_fields(care_raw)
    conf = data.get("confidence") if isinstance(data.get("confidence"), dict) else {}
    return {
        "roles": roles,
        "garment": _garment_fields(garment_raw, partial=True),
        "logo_brand": str(garment_raw.get("logo_brand") or "").strip()[:40],
        "labels": {
            "brand": str(labels_raw.get("brand") or "").strip()[:40],
            "size_label": str(labels_raw.get("size_label") or "").strip()[:20],
            "composition": str(labels_raw.get("composition") or "").strip()[:120],
            "care": care,
        },
        "confidence": {"garment": _confidence(conf.get("garment")), "labels": _confidence(conf.get("labels"))},
    }


# ---------------------------------------------------------------- fit critique

def critique_fit(provider, image, garment: dict, verdicts: list[dict], log: dict) -> str:
    facts = {
        "garment": {k: garment.get(k) for k in ("name", "category", "subcategory", "brand",
                                                  "size_label", "fit_type", "material")},
        "measured_fit": verdicts,
        "wearer_feedback": {"overall": log.get("overall"), "areas": log.get("areas"),
                            "notes": log.get("notes")},
    }
    prompt = f"""This photo shows someone wearing the garment described below. Assess how the
GARMENT fits (not the person). Check the points that apply: shoulder seam position, chest and
button pull, sleeve and hem length, trouser break, waist gap, drag lines, how the intended fit
({garment.get('fit_type', 'regular')}) comes across.

Facts: {json.dumps(facts, ensure_ascii=False)}

Write 4 short parts with these headings: "Verdict" (one sentence), "Works", "Off",
"Fix" (alterations or a better size, cheapest first). Keep it under 140 words."""
    return provider.ask(prompt, images=[image], system=SYSTEM).strip()


# ---------------------------------------------------------------- styling

def style_looks(provider, candidates: list[dict], context: dict) -> list[dict]:
    lines = []
    for i, look in enumerate(candidates):
        items = "; ".join(
            f"{g['name']} ({g['category']}, {', '.join(colors.name_of(c) for c in g['colors'][:2]) or 'colour unknown'}, "
            f"{g.get('pattern', 'solid')}, formality {g.get('formality')})" for g in look["items"])
        lines.append(f"{i}: {items}")
    prompt = f"""Context: {json.dumps(context, ensure_ascii=False)}
Candidate outfits (index: items):
{chr(10).join(lines)}

Pick the 3 strongest outfits for this context. Return JSON:
{{"picks": [{{"index": <int>, "why": "<one sentence>", "tip": "<one concrete styling tip: tuck, roll, layer, accessory>"}}]}}"""
    data = parse_json(provider.ask(prompt, want_json=True, system=SYSTEM))
    picks = []
    for p in data.get("picks", [])[:3]:
        idx = _clamp(p.get("index"), 0, len(candidates) - 1, -1)
        if idx >= 0 and all(x["index"] != idx for x in picks):
            picks.append({"index": idx, "why": str(p.get("why", ""))[:240],
                          "tip": str(p.get("tip", ""))[:240]})
    if not picks:
        raise AIError("AI did not pick any outfit")
    return picks


# ---------------------------------------------------------------- shopping

def shopping_advice(provider, summary: dict) -> str:
    prompt = f"""Here is a summary of one person's wardrobe and a rule-based gap analysis.
{json.dumps(summary, ensure_ascii=False)}

Give shopping advice in this shape:
1. "Buy next": the 3 purchases that add the most outfits, each with colour, fabric and fit
   to look for, and why it works with what they own.
2. "Skip": 2 things they should not buy more of, based on what they already own.
3. "Before buying": one habit or alteration that would get more out of the current wardrobe.
They live in the Netherlands (mild, wet climate). Under 220 words, plain text."""
    return provider.ask(prompt, system=SYSTEM).strip()
