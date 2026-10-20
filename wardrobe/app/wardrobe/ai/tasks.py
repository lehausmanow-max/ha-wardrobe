"""The five AI jobs, each with a prompt and strict validation of what comes back."""

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
    category = _pick(data.get("category"), taxonomy.CATEGORIES, "top")
    hexes = [h for h in (colors.normalize_hex(c) for c in (data.get("colors") or [])) if h][:3]
    return {
        "name": str(data.get("name") or "").strip()[:60],
        "category": category,
        "subcategory": _pick(data.get("subcategory"), taxonomy.CATEGORIES[category]["sub"], ""),
        "colors": hexes,
        "pattern": _pick(data.get("pattern"), taxonomy.PATTERNS, "solid"),
        "material": str(data.get("material") or "").strip().lower()[:60],
        "formality": _clamp(data.get("formality"), 1, 5, 3),
        "warmth": _clamp(data.get("warmth"), 1, 5, 3),
        "seasons": _list(data.get("seasons"), taxonomy.SEASONS),
        "occasions": _list(data.get("occasions"), taxonomy.OCCASIONS),
        "brand": str(data.get("brand") or "").strip()[:40],
    }


# ---------------------------------------------------------------- care label

def read_care_label(provider, image) -> dict:
    f = taxonomy.CARE_FIELDS
    prompt = f"""This is a photo of a garment's care label (ISO/GINETEX laundry symbols and/or text).
Read it and return JSON with:
- "composition": fibre composition as written, e.g. "80% wool, 20% polyamide" ("" if not visible)
- "wash": one of {f['wash']}  (tub = machine, hand in tub = hand, crossed tub = no_wash)
- "temp": maximum wash temperature in °C, one of {f['temp']} or null (dots: 1=30, 2=40, 3=50/60)
- "cycle": one of {f['cycle']} (one bar under tub = delicate, two bars = wool/very gentle)
- "bleach": one of {f['bleach']}
- "dry": one of {f['dry']} (square with circle = tumble; dots = heat; crossed = no_tumble; square with line = line/flat)
- "iron": one of {f['iron']} (dots: 1=low, 2=medium, 3=high)
- "dry_clean": one of {f['dry_clean']}
- "notes": any extra text instructions, e.g. "wash inside out" ("" if none)
- "confidence": "high", "medium" or "low"
"""
    data = parse_json(provider.ask(prompt, images=[image], want_json=True, system=SYSTEM))
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
        "bleach": _pick(data.get("bleach"), f["bleach"], "no"),
        "dry": _pick(data.get("dry"), f["dry"], "line"),
        "iron": _pick(data.get("iron"), f["iron"], "medium"),
        "dry_clean": _pick(data.get("dry_clean"), [x.lower() for x in f["dry_clean"]], "any"),
        "notes": str(data.get("notes") or "")[:200],
    }
    if care["dry_clean"] in ("p", "f"):
        care["dry_clean"] = care["dry_clean"].upper()
    return {"care": care, "composition": str(data.get("composition") or "")[:120],
            "confidence": _pick(data.get("confidence"), ["high", "medium", "low"], "medium")}


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
