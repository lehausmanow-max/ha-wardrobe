"""Outfit engine: rule-based scoring plus a beam search over the wardrobe.

Opinionated defaults:
- one accent colour on a neutral base beats a rainbow
- one loud pattern per outfit
- formality within one step across pieces
- dress for the temperature, not the season label
"""

from datetime import date, timedelta

from . import colors, taxonomy

UPPER = ("top", "knitwear", "dress")
GOOD_SCORE = 70


def season_of(d: date) -> str:
    m = d.month
    return ("winter", "winter", "spring", "spring", "spring", "summer",
            "summer", "summer", "autumn", "autumn", "autumn", "winter")[m - 1]


def warmth_window(temp: float) -> tuple[int, int]:
    """Comfortable total warmth of the upper-body layers at a temperature (°C)."""
    if temp >= 25:
        return 1, 2
    if temp >= 20:
        return 1, 3
    if temp >= 15:
        return 2, 5
    if temp >= 10:
        return 4, 8
    if temp >= 5:
        return 6, 10
    if temp >= 0:
        return 8, 12
    return 10, 15


class Context:
    def __init__(self, occasion: str | None = None, temp: float | None = None,
                 on: date | None = None, last_worn: dict | None = None,
                 look_ratings: dict | None = None, rain: bool = False):
        self.occasion = occasion if occasion in taxonomy.OCCASIONS else None
        self.target_formality = taxonomy.OCCASION_FORMALITY.get(self.occasion) if self.occasion else None
        self.temp = temp
        self.on = on or date.today()
        self.season = season_of(self.on)
        self.last_worn = last_worn or {}
        self.look_ratings = look_ratings or {}
        self.rain = bool(rain)

    def public(self) -> dict:
        return {"occasion": self.occasion, "temperature_c": self.temp, "season": self.season,
                "target_formality": self.target_formality, "rain": self.rain}


def _main(g: dict) -> str | None:
    cs = g.get("colors") or []
    return cs[0] if cs else None


RAIN_OUTER = {"rain jacket", "trench"}


def rain_ready(g: dict) -> bool:
    return g["category"] == "outerwear" and (
        g.get("subcategory") in RAIN_OUTER or "waterproof" in (g.get("notes") or "").lower())


def _suede(g: dict) -> bool:
    text = " ".join(str(g.get(k) or "") for k in ("material", "name", "notes")).lower()
    return "suede" in text


def _upper_warmth(items) -> int:
    return sum(int(g.get("warmth") or 3) for g in items
               if g["category"] in ("top", "knitwear", "dress", "outerwear"))


def score(items: list[dict], ctx: Context, with_weather: bool = True) -> dict:
    reasons, warnings = [], []

    # Colour
    col_score, col_reason = colors.harmony([c for c in (_main(g) for g in items) if c])
    reasons.append(col_reason)

    # Pattern
    loud = [g for g in items if (g.get("pattern") or "solid") not in taxonomy.QUIET_PATTERNS]
    if len(loud) <= 1:
        pat_score = 100
        if loud:
            reasons.append(f"The {loud[0].get('pattern')} on the {loud[0]['name'].lower()} is the focal point")
    elif len(loud) == 2:
        kinds = {g.get("pattern") for g in loud}
        pat_score = 72 if kinds == {"stripe", "check"} or len(kinds) == 1 else 55
        warnings.append("Two patterns: keep their scale different")
    else:
        pat_score = 25
        warnings.append("Three or more patterns")

    # Formality
    # Outerwear is left out: a rain jacket over tailoring is normal in this climate.
    forms = [int(g.get("formality") or 3) for g in items if g["category"] not in ("accessory", "outerwear")]
    spread = max(forms) - min(forms) if forms else 0
    form_score = {0: 100, 1: 96}.get(spread, 70 if spread == 2 else 25)
    if spread >= 2:
        warnings.append("Mixes dressy and casual pieces")
    if ctx.target_formality and forms:
        gap = abs(sum(forms) / len(forms) - ctx.target_formality)
        form_score -= int(gap * 14)
        if gap >= 1.25:
            warnings.append(f"{'Too dressed up' if sum(forms) / len(forms) > ctx.target_formality else 'Too casual'} for {ctx.occasion}")

    # Weather
    w_score = 85
    if with_weather and ctx.temp is not None:
        lo, hi = warmth_window(ctx.temp)
        w = _upper_warmth(items)
        if lo <= w <= hi:
            w_score = 100
            reasons.append(f"Right weight for {ctx.temp:.0f} °C")
        else:
            off = lo - w if w < lo else w - hi
            w_score = max(10, 100 - off * 18)
            warnings.append(f"{'Too light' if w < lo else 'Too warm'} for {ctx.temp:.0f} °C")
        has_outer = any(g["category"] == "outerwear" for g in items)
        if ctx.temp < 12 and not has_outer:
            w_score -= 25
            warnings.append("Needs a jacket or coat")
        if ctx.temp >= 22 and has_outer:
            w_score -= 25
        if ctx.temp >= 21:
            heavy = [g for g in items if g["category"] == "knitwear" and int(g.get("warmth") or 3) >= 3]
            heavy += [g for g in items if g.get("subcategory") == "boots"]
            if heavy:
                w_score -= 15 * len(heavy)
                warnings.append(f"{heavy[0]['name']} is warm for {ctx.temp:.0f} °C")
        if ctx.temp < 14 and any(g.get("subcategory") in ("shorts", "sandals") for g in items):
            w_score -= 30
            warnings.append("Shorts or sandals in this weather")

    # Rain: small nudges on top of the weather score.
    if with_weather and ctx.rain:
        if any(rain_ready(g) for g in items):
            w_score += 6
            reasons.append("Rain-ready")
        else:
            w_score -= 6
            warnings.append("Rain likely: take a rain jacket")
        for g in items:
            if g["category"] != "shoes":
                continue
            if _suede(g):
                w_score -= 8
                warnings.append(f"Suede in the rain: the {g['name'].lower()} may stain")
            elif g.get("subcategory") == "sandals":
                w_score -= 8
                warnings.append("Sandals in the rain")

    season_misses = [g for g in items if g.get("seasons") and ctx.season not in g["seasons"]]
    w_score -= 8 * len(season_misses)

    total = 0.36 * col_score + 0.16 * pat_score + 0.24 * form_score + 0.24 * w_score

    # Occasion tags, rotation, favourites, history
    if ctx.occasion:
        for g in items:
            occ = g.get("occasions") or []
            if occ:
                total += 1.5 if ctx.occasion in occ else -3
    stale_cut = ctx.on - timedelta(days=30)
    for g in items:
        lw = ctx.last_worn.get(g["id"])
        if lw:
            days = (ctx.on - lw).days
            if days <= 2:
                total -= 12
                warnings.append(f"Wore the {g['name'].lower()} {'today' if days == 0 else 'recently'}")
            elif days <= 6:
                total -= 4
            elif lw < stale_cut:
                total += 1  # rested pieces come back into rotation
        if g.get("favorite"):
            total += 1
    key = frozenset(g["id"] for g in items)
    if key in ctx.look_ratings:
        rating = ctx.look_ratings[key] or 3
        total += (rating - 3) * 3
        reasons.append("A saved look")

    return {"score": max(0, min(100, round(total))), "reasons": reasons, "warnings": warnings,
            "parts": {"colour": col_score, "pattern": pat_score, "formality": form_score,
                      "weather": w_score}}


def _by_cat(garments):
    out = {k: [] for k in taxonomy.CATEGORIES}
    for g in garments:
        if g.get("status", "active") == "active" and g["category"] in out:
            out[g["category"]].append(g)
    return out


LAYER_ONLY = {"cardigan", "vest", "gilet"}


def _bases(cats):
    for t in cats["top"] + [k for k in cats["knitwear"] if k.get("subcategory") not in LAYER_ONLY]:
        for b in cats["bottom"]:
            yield (t, b)
    for d in cats["dress"]:
        yield (d,)


def suggest(garments: list[dict], ctx: Context, anchor_id: int | None = None,
            count: int = 6) -> list[dict]:
    cats = _by_cat(garments)
    anchor = next((g for g in garments if g["id"] == anchor_id), None) if anchor_id else None
    cold = ctx.temp is not None and ctx.temp < 14
    hot = ctx.temp is not None and ctx.temp >= 22

    # 1. Base pairs, scored without weather to judge the core combination.
    bases = [b for b in _bases(cats)
             if anchor is None or anchor["category"] not in ("top", "bottom", "dress", "knitwear")
             or anchor in b or (anchor["category"] == "knitwear" and b[0]["category"] == "top")]
    bases.sort(key=lambda b: score(list(b), ctx, with_weather=False)["score"], reverse=True)
    bases = bases[:60]

    # 2. Shoes.
    shoes = cats["shoes"]
    if anchor and anchor["category"] == "shoes":
        shoes = [anchor]
    with_shoes = []
    for b in bases:
        if shoes:
            for s in shoes:
                with_shoes.append(list(b) + [s])
        else:
            with_shoes.append(list(b))
    with_shoes.sort(key=lambda o: score(o, ctx, with_weather=False)["score"], reverse=True)
    with_shoes = with_shoes[:90]

    # 3. Layers.
    mids = cats["knitwear"]
    outers = cats["outerwear"]
    if anchor and anchor["category"] == "outerwear":
        outers = [anchor]
    if anchor and anchor["category"] == "knitwear":
        mids = [anchor]
    tf = ctx.target_formality or 3
    mids = sorted(mids, key=lambda g: abs(int(g.get("formality") or 3) - tf))[:6]
    outers = sorted(outers, key=lambda g: (ctx.rain and not rain_ready(g),
                                           abs(int(g.get("formality") or 3) - tf)))[:6]

    candidates = []
    for o in with_shoes:
        variants = [o]
        if not hot:
            top_is_tee = o[0]["category"] == "top"
            variants += [o + [m] for m in mids if top_is_tee and m not in o]
            variants += [o + [x] for x in outers]
            if cold:
                variants += [o + [m, x] for m in mids for x in outers if top_is_tee and m not in o]
        for v in variants:
            if anchor and anchor not in v:
                continue
            s = score(v, ctx)
            candidates.append((s["score"], v, s))

    candidates.sort(key=lambda c: c[0], reverse=True)

    # 4. Pick a varied set: no repeated core, and no piece in more than a couple of looks.
    #    Small wardrobes get a second, looser pass so the list still fills up.
    chosen, seen_cores = [], []
    # Pass 1 wants strong, varied looks; pass 2 relaxes variety, never quality below 60.
    for cap_core, cap_other, floor in ((2, 3, 75), (3, 5, 60)):
        used: dict[int, int] = {}
        for lk in chosen:
            for g in lk["items"]:
                used[g["id"]] = used.get(g["id"], 0) + 1
        for sc, items, s in candidates:
            if len(chosen) >= count or sc < floor:
                break
            core = frozenset(g["id"] for g in items if g["category"] in ("top", "knitwear", "bottom", "dress"))
            if core in seen_cores:
                continue
            over = [g for g in items if g is not anchor and used.get(g["id"], 0) >=
                    (cap_core if g["category"] in ("top", "knitwear", "bottom", "dress") else cap_other)]
            if over:
                continue
            seen_cores.append(core)
            for g in items:
                used[g["id"]] = used.get(g["id"], 0) + 1
            chosen.append({"score": sc, "items": _order(items),
                           **{k: s[k] for k in ("reasons", "warnings", "parts")}})
    chosen.sort(key=lambda lk: lk["score"], reverse=True)
    return chosen


ORDER = {"outerwear": 0, "knitwear": 1, "top": 2, "dress": 2, "bottom": 3, "shoes": 4, "accessory": 5}


def _order(items):
    return sorted(items, key=lambda g: ORDER.get(g["category"], 9))


# ------------------------------------------------------------- wardrobe-wide counts

def valid_outfits(garments: list[dict], ctx: Context, threshold: int = GOOD_SCORE):
    """Every core outfit (base + shoes) that scores well, weather ignored."""
    cats = _by_cat(garments)
    shoes = cats["shoes"] or [None]
    for b in _bases(cats):
        for s in shoes:
            items = list(b) + ([s] if s else [])
            sc = score(items, ctx, with_weather=False)["score"]
            if sc >= threshold:
                yield items


def per_item_counts(garments: list[dict], ctx: Context) -> dict[int, int]:
    counts = {g["id"]: 0 for g in garments}
    total = 0
    for items in valid_outfits(garments, ctx):
        total += 1
        for g in items:
            counts[g["id"]] += 1
    counts["_total"] = total
    return counts


def unlock_count(garments: list[dict], candidate: dict, ctx: Context) -> int:
    """How many new good core outfits a hypothetical garment would create."""
    cats = _by_cat(garments)
    c = candidate
    n = 0
    shoes = cats["shoes"] or [None]

    def ok(items):
        return score([i for i in items if i], ctx, with_weather=False)["score"] >= GOOD_SCORE

    if c["category"] in ("top", "knitwear") and c.get("subcategory") not in LAYER_ONLY:
        n = sum(ok([c, b, s]) for b in cats["bottom"] for s in shoes)
    elif c["category"] == "bottom":
        n = sum(ok([t, c, s]) for t in cats["top"] + cats["knitwear"] for s in shoes)
    elif c["category"] == "dress":
        n = sum(ok([c, s]) for s in shoes)
    elif c["category"] == "shoes":
        n = sum(ok(list(b) + [c]) for b in _bases(cats))
    return n

