"""Fit assessment from measurements (ease = garment - body) and from wear logs."""

from statistics import mean

from . import taxonomy

# Ease windows in cm for each intended fit: (tight_below, good_from, good_to, loose_above).
CHEST_EASE = {
    "slim": (2, 4, 9, 14),
    "regular": (5, 8, 15, 20),
    "relaxed": (10, 14, 22, 30),
    "oversized": (16, 22, 40, 55),
}
# Layering pieces need room for what goes underneath.
LAYER_EXTRA = {"outerwear": 6, "knitwear": -2}  # knits stretch and sit closer

HIP_EASE = {
    "slim": (0, 2, 6, 9), "regular": (2, 4, 10, 14),
    "relaxed": (6, 8, 16, 22), "oversized": (10, 14, 26, 34),
}
WAIST_BOTTOM = (-1, 0, 4, 7)       # trousers sit close at the waist whatever the cut
WAIST_TOP = {"slim": (2, 4, 10, 16), "regular": (6, 10, 20, 28),
             "relaxed": (12, 16, 30, 40), "oversized": (20, 26, 50, 70)}
SHOULDER = {"slim": (-2, -1, 1.5, 3), "regular": (-2, -1, 2, 3.5),
            "relaxed": (-1, 0, 4, 6), "oversized": (1, 3, 12, 16)}
SLEEVE = (-3, -1.5, 2, 4)
INSEAM = (-5, -3, 2, 4)

LABELS = {"tight": "too tight", "snug": "snug", "good": "right", "roomy": "roomy", "loose": "too loose"}
SHORT_LONG = {"tight": "too short", "snug": "a touch short", "good": "right",
              "roomy": "a touch long", "loose": "too long"}


def _band(ease: float, window) -> str:
    tight, good_lo, good_hi, loose = window
    if ease < tight:
        return "tight"
    if ease < good_lo:
        return "snug"
    if ease <= good_hi:
        return "good"
    if ease <= loose:
        return "roomy"
    return "loose"


def assess(garment: dict, body: dict) -> list[dict]:
    """Compare garment measurements with body measurements. Returns one verdict per key."""
    gm = garment.get("measurements") or {}
    cat = garment.get("category", "")
    fit_type = garment.get("fit_type") or "regular"
    if fit_type not in taxonomy.FIT_TYPES:
        fit_type = "regular"
    extra = LAYER_EXTRA.get(cat, 0)
    out = []

    def num(d, k):
        try:
            v = float(d.get(k))
            return v if v > 0 else None
        except (TypeError, ValueError):
            return None

    def add(key, label, window, words=LABELS, body_key=None):
        g, b = num(gm, key), num(body, body_key or key)
        if g is None or b is None:
            return
        ease = round(g - b, 1)
        band = _band(ease, window)
        out.append({"key": key, "label": label, "garment": g, "body": b, "ease": ease,
                    "band": band, "verdict": words[band]})

    if cat in ("top", "knitwear", "outerwear", "dress"):
        lo = CHEST_EASE[fit_type]
        add("chest", "Chest", tuple(x + extra for x in lo))
        add("shoulder", "Shoulders", SHOULDER[fit_type])
        if cat != "dress":
            add("sleeve", "Sleeves", SLEEVE, SHORT_LONG)
        add("waist", "Waist", WAIST_TOP[fit_type])
        if cat == "dress":
            add("hips", "Hips", HIP_EASE[fit_type])
    elif cat == "bottom":
        add("waist", "Waist", WAIST_BOTTOM)
        add("hips", "Hips", HIP_EASE[fit_type])
        add("inseam", "Inseam", INSEAM, SHORT_LONG)
    elif cat == "shoes":
        g, b = num(gm, "shoe_eu"), num(body, "shoe_eu")
        if g and b:
            d = round(g - b, 1)
            band = "good" if abs(d) <= 0.5 else ("snug" if -1 <= d < 0 else
                                                  "roomy" if 0 < d <= 1 else "tight" if d < 0 else "loose")
            out.append({"key": "shoe_eu", "label": "Size", "garment": g, "body": b, "ease": d,
                        "band": band, "verdict": LABELS[band]})
    return out


def summary(verdicts: list[dict]) -> str:
    if not verdicts:
        return ""
    bad = [v for v in verdicts if v["band"] in ("tight", "loose")]
    near = [v for v in verdicts if v["band"] in ("snug", "roomy")]
    if not bad and not near:
        return "Measures right everywhere you've recorded"
    parts = [f"{v['label'].lower()} {v['verdict']}" for v in bad + near]
    return ("Check fit: " if bad else "Close: ") + ", ".join(parts)


def brand_notes(garments: list[dict], logs_by_garment: dict[int, list[dict]]) -> list[dict]:
    """How sizes run per brand, from what you said in fit logs."""
    agg: dict[tuple[str, str], list[int]] = {}
    for g in garments:
        brand = (g.get("brand") or "").strip()
        if not brand:
            continue
        for log in logs_by_garment.get(g["id"], []):
            score = taxonomy.FIT_OVERALL_SCORE.get(log.get("overall"))
            if score is not None:
                agg.setdefault((brand, (g.get("size_label") or "?").strip()), []).append(score)
    notes = []
    for (brand, size), scores in sorted(agg.items()):
        avg = mean(scores)
        if avg <= -1.25:
            runs = "runs small, size up"
        elif avg <= -0.4:
            runs = "runs slightly small"
        elif avg < 0.4:
            runs = "true to size"
        elif avg < 1.25:
            runs = "runs slightly large"
        else:
            runs = "runs large, size down"
        notes.append({"brand": brand, "size": size, "logs": len(scores),
                      "average": round(avg, 2), "advice": runs})
    return notes
