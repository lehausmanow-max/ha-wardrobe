"""Shopping suggestions: what to buy next (by outfits unlocked), coverage gaps, and what to stop buying."""

from datetime import date, timedelta

from . import colors, matching

# Hard-working archetypes to test against the wardrobe. Dress archetypes only run
# for profiles that already own dresses.
ARCHETYPES = [
    ("Plain white T-shirt", "top", "t-shirt", "#f6f6f3", 1, 2, "cotton"),
    ("Black fine-knit top", "top", "long sleeve", "#1a1a1a", 3, 2, "merino"),
    ("White Oxford shirt", "top", "shirt", "#f3f3ef", 3, 2, "cotton"),
    ("Light blue shirt", "top", "shirt", "#a9c4e0", 3, 2, "cotton"),
    ("Navy crewneck sweater", "knitwear", "sweater", "#24304a", 3, 3, "merino"),
    ("Grey crewneck sweater", "knitwear", "sweater", "#8a8b8d", 3, 3, "wool"),
    ("Cream cable knit", "knitwear", "sweater", "#ece4d2", 2, 4, "wool"),
    ("Dark indigo jeans", "bottom", "jeans", "#2c3a57", 2, 3, "denim"),
    ("Navy tailored trousers", "bottom", "trousers", "#1f2a44", 4, 3, "wool"),
    ("Grey wool trousers", "bottom", "trousers", "#6f7073", 4, 3, "wool"),
    ("Beige chinos", "bottom", "chinos", "#c9b48d", 3, 2, "cotton"),
    ("Black straight trousers", "bottom", "trousers", "#1a1a1a", 3, 3, "polyester"),
    ("White leather sneakers", "shoes", "sneakers", "#f2f2ef", 2, 2, "leather"),
    ("Dark brown leather boots", "shoes", "boots", "#3f2a1f", 3, 3, "leather"),
    ("Black leather shoes", "shoes", "dress shoes", "#161616", 4, 2, "leather"),
    ("Suede loafers in tan", "shoes", "loafers", "#a7774b", 3, 2, "suede"),
    ("Black midi dress", "dress", "dress", "#1a1a1a", 3, 2, "viscose"),
    ("Navy shirt dress", "dress", "dress", "#24304a", 3, 2, "cotton"),
]


def _archetype(entry) -> dict:
    name, cat, sub, hx, form, warmth, material = entry
    return {"id": -1, "name": name, "category": cat, "subcategory": sub, "colors": [hx],
            "pattern": "solid", "formality": form, "warmth": warmth, "material": material,
            "seasons": [], "occasions": [], "status": "active"}


def _covered(garments, cand) -> dict | None:
    """Do they already own something that does the same job?"""
    for g in garments:
        if g["category"] != cand["category"] or not g.get("colors"):
            continue
        same_job = (g.get("subcategory") == cand["subcategory"]
                    or cand["category"] in ("knitwear", "shoes"))
        if same_job and colors.delta_e(g["colors"][0], cand["colors"][0]) < 20 \
                and abs(int(g.get("formality") or 3) - cand["formality"]) <= 1:
            return g
    return None


def analyse(garments: list[dict], wears: dict[int, list[date]], today: date | None = None) -> dict:
    today = today or date.today()
    # Pieces in the wash or at the tailor still count as owned.
    active = [g | {"status": "active"} for g in garments if g.get("status") in ("active", "laundry", "repair")]
    ctx = matching.Context(on=today)
    owns_dresses = any(g["category"] == "dress" for g in active)

    # 1. Best next buys, ranked by new good outfits.
    buys = []
    for entry in ARCHETYPES:
        cand = _archetype(entry)
        if cand["category"] == "dress" and not owns_dresses:
            continue
        if cand["category"] == "outerwear":
            continue  # layers are judged by coverage below, not by outfit count
        if _covered(active, cand):
            continue
        n = matching.unlock_count(active, cand, ctx)
        if n > 0:
            buys.append({"name": cand["name"], "category": cand["category"], "color": cand["colors"][0],
                         "material": cand["material"], "unlocks": n})
    buys.sort(key=lambda b: b["unlocks"], reverse=True)

    # 2. Coverage gaps: plain rules that don't need maths.
    by_cat: dict[str, list] = {}
    for g in active:
        by_cat.setdefault(g["category"], []).append(g)
    gaps = []
    if not by_cat.get("shoes"):
        gaps.append("No shoes recorded yet, so outfits can't be finished")
    if not any(g.get("subcategory") == "rain jacket" or "waterproof" in (g.get("notes") or "").lower()
               for g in by_cat.get("outerwear", [])):
        gaps.append("No rain jacket: in Dutch weather that's the most-worn layer")
    if not any(int(g.get("warmth") or 0) >= 4 for g in by_cat.get("outerwear", [])):
        gaps.append("Nothing warm enough for winter (outerwear with warmth 4 or more)")
    if not any(int(g.get("formality") or 0) >= 4 for g in by_cat.get("outerwear", [])):
        gaps.append("No smart layer (blazer or tailored coat) for work and occasions")
    if not any(int(g.get("formality") or 0) >= 4 for g in by_cat.get("shoes", [])) and by_cat.get("shoes"):
        gaps.append("No smart shoes for formal occasions")
    tops = len(by_cat.get("top", [])) + len(by_cat.get("knitwear", []))
    bottoms = len(by_cat.get("bottom", []))
    if bottoms and tops / bottoms > 4:
        gaps.append(f"{tops} tops for {bottoms} bottoms: another neutral bottom multiplies outfits fastest")
    if tops and bottoms / tops > 1.5:
        gaps.append(f"{bottoms} bottoms for {tops} tops: add tops before more bottoms")

    # 3. Hard to style and underused.
    counts = matching.per_item_counts(active, ctx)
    hard = [{"id": g["id"], "name": g["name"], "category": g["category"]}
            for g in active if g["category"] in ("top", "knitwear", "bottom", "dress", "shoes")
            and g.get("subcategory") not in matching.LAYER_ONLY and counts.get(g["id"], 0) == 0]
    cutoff = today - timedelta(days=90)
    underused, cpw = [], []
    for g in active:
        worn = wears.get(g["id"], [])
        added = (g.get("created_at") or "")[:10]
        old_enough = added and added <= cutoff.isoformat()
        if old_enough and (not worn or max(worn) < cutoff):
            underused.append({"id": g["id"], "name": g["name"], "last_worn": max(worn).isoformat() if worn else None})
        if g.get("price") and worn:
            cpw.append({"id": g["id"], "name": g["name"], "price": g["price"], "wears": len(worn),
                        "cost_per_wear": round(g["price"] / max(1, len(worn)), 2)})
    cpw.sort(key=lambda r: r["cost_per_wear"], reverse=True)

    # 4. Stop buying: categories already saturated.
    saturated = []
    for cat, items in by_cat.items():
        if cat in ("top", "knitwear") and len(items) >= 12:
            per_colour: dict[str, int] = {}
            for g in items:
                if g.get("colors"):
                    per_colour[colors.name_of(g["colors"][0])] = per_colour.get(colors.name_of(g["colors"][0]), 0) + 1
            for col, n in per_colour.items():
                if n >= 4:
                    saturated.append(f"{n} {col} {cat}s already")

    return {
        "total_outfits": counts.get("_total", 0),
        "buys": buys[:8],
        "gaps": gaps,
        "hard_to_style": hard,
        "underused": underused[:12],
        "cost_per_wear": cpw[:10],
        "saturated": saturated,
        "counts": {cat: len(v) for cat, v in by_cat.items()},
    }
