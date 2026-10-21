"""One-pass intake: read all photos of a garment at once and merge what they say.

Labels and tags beat the photo for composition, brand, size and care. Bleach only ever comes from a
care label. On a draft the result is written straight in; on a saved garment it comes back as
proposals, so nothing the owner typed is replaced without asking.
"""

from . import ai, care, images

READ_KINDS = ("item", "label", "tag")  # never "worn": those photos show a person
MAX_PHOTOS = 6
ROLE_KIND = {"front": "item", "back": "item", "detail": "item", "other": "item",
             "care_label": "label", "brand_tag": "tag"}
KIND_HINT = {"item": "photo of the garment itself", "label": "care label", "tag": "brand or size tag"}

GARMENT_FIELDS = ("name", "category", "subcategory", "colors", "pattern", "formality", "warmth",
                  "seasons", "occasions")
# Fields a label or tag decides. A proposal for one of these, read from a label or tag, is ticked.
LABEL_FIELDS = ("material", "care", "brand", "size_label")
# Order of rows in the review of a re-read.
FIELD_ORDER = ("material", "care", "brand", "size_label", "name", "category", "subcategory", "colors",
               "pattern", "formality", "warmth", "seasons", "occasions")
CARE_COMPARE = ("wash", "temp", "cycle", "bleach", "dry", "iron", "dry_clean", "notes", "wash_after")


def pick_photos(photos: list[dict]) -> list[dict]:
    """The photos to read: the main photo, then labels and tags, then other garment photos. At most 6."""
    usable = [p for p in photos if p["kind"] in READ_KINDS]

    def rank(p):
        if p["is_primary"]:
            return (0, p["id"])
        return (1 if p["kind"] != "item" else 2, p["id"])

    return sorted(usable, key=rank)[:MAX_PHOTOS]


def read(provider, photos: list[dict], keep=()) -> dict:
    """Ask the vision provider about the photos. Returns roles keyed by photo id, garment fields,
    logo_brand, labels and confidence. Raises ai.AIError."""
    chosen = pick_photos(photos)
    if provider.name == "ollama":
        return _read_one_by_one(provider, chosen)
    imgs = [images.for_ai(p["filename"], side=images.READ_SIDE) for p in chosen]
    hints = {i + 1: KIND_HINT[p["kind"]] for i, p in enumerate(chosen) if p["id"] in keep}
    result = ai.tasks.read_garment(provider, imgs, hints)
    result["roles"] = {p["id"]: role for p, role in zip(chosen, result["roles"], strict=True)}
    return result


def _read_one_by_one(provider, chosen: list[dict]) -> dict:
    """Small local models handle several images poorly: tag the main photo, read each care label.
    Photo kinds stay as the owner set them."""
    items = [p for p in chosen if p["kind"] == "item"]
    garment, logo = {}, ""
    if items:
        tags = ai.tasks.tag_garment(provider, images.for_ai(items[0]["filename"]))
        logo = tags.pop("brand", "")
        garment = {k: v for k, v in tags.items() if v not in ("", [], None)}
    label_care, composition, confidence = None, "", "medium"
    for p in (p for p in chosen if p["kind"] == "label"):
        res = ai.tasks.read_care_label(provider, images.for_ai(p["filename"], side=images.READ_SIDE))
        if label_care is None:
            label_care, confidence = res["care"], res["confidence"]
        composition = composition or res["composition"]
    return {"roles": {}, "garment": garment, "logo_brand": logo,
            "labels": {"brand": "", "size_label": "", "composition": composition, "care": label_care},
            "confidence": {"garment": "medium", "labels": confidence}}


def kinds_after(photos: list[dict], roles: dict, keep=()) -> dict[int, str]:
    """Photo kind per photo id once the roles from a read are applied. Kinds the owner set stay."""
    out = {}
    for p in photos:
        role = roles.get(p["id"])
        out[p["id"]] = ROLE_KIND[role] if role and p["id"] not in keep and p["kind"] in READ_KINDS else p["kind"]
    return out


def merge(garment: dict, result: dict, fresh: bool, kinds: set[str], local_colors=None) -> dict:
    """What the read says, as {field: (value, source)}. Sources: label, tag, photo, defaults.

    fresh: the garment is a draft, so nothing in it was typed by the owner.
    kinds: photo kinds present after the read, to tell a care label from a brand tag.
    """
    out = {}
    seen = result.get("garment") or {}
    for k in GARMENT_FIELDS:
        v = seen.get(k)
        if v not in (None, "", []):
            out[k] = (v, "photo")
    if "colors" not in out and local_colors:
        out["colors"] = (list(local_colors), "photo")

    labels = result.get("labels") or {}
    tag_source = "tag" if "tag" in kinds else "label"
    composition_source = "label" if "label" in kinds else "tag"
    if labels.get("composition"):
        out["material"] = (labels["composition"].lower(), composition_source)
    elif seen.get("material"):
        out["material"] = (seen["material"], "photo")
    if labels.get("brand"):
        out["brand"] = (labels["brand"], tag_source)
    elif result.get("logo_brand"):
        out["brand"] = (result["logo_brand"], "photo")
    if labels.get("size_label"):
        out["size_label"] = (labels["size_label"], tag_source)

    material = out["material"][0] if "material" in out else (garment.get("material") or "")
    category = out["category"][0] if "category" in out else garment.get("category") or "top"
    stored = garment.get("care") or {}
    defaults = care.defaults_for(material, category)
    if labels.get("care"):
        c = {k: v for k, v in labels["care"].items() if k != "bleach_from_label" and v is not None}
        # The label decides bleach: a symbol read now replaces the old value, no symbol clears it.
        if c.get("bleach"):
            c["bleach_from_label"] = True
        c["wash_after"] = (not fresh and stored.get("wash_after")) or defaults["wash_after"]
        if not c.get("notes"):
            c["notes"] = defaults["notes"] if fresh else (stored.get("notes") or "")
        out["care"] = (c, "label")
    elif fresh or ("material" in out and not same("material", garment.get("material"), material)):
        # No care label read: fibre defaults. On a saved garment only when the fabric changed.
        d = {k: v for k, v in defaults.items() if v is not None}
        if not fresh and stored.get("wash_after"):
            d["wash_after"] = stored["wash_after"]
        out["care"] = (care.label_bleach(d, stored), "defaults")
    return out


def _empty(v) -> bool:
    if isinstance(v, dict):
        return not v.get("wash")
    return v in (None, "", [])


def same(field: str, old, new) -> bool:
    if field in ("seasons", "occasions"):
        return set(old or []) == set(new or [])
    if field == "colors":
        return [c.lower() for c in old or []] == [c.lower() for c in new or []]
    if field == "care":
        old, new = old or {}, new or {}
        return all((old.get(k) or None) == (new.get(k) or None) for k in CARE_COMPARE)
    if isinstance(old, str) or isinstance(new, str):
        return str(old or "").strip().casefold() == str(new or "").strip().casefold()
    return old == new


def proposals(garment: dict, merged: dict) -> list[dict]:
    """Rows for the review sheet: only fields that would change. default_on means ticked."""
    rows = []
    for field in FIELD_ORDER:
        if field not in merged:
            continue
        new, source = merged[field]
        old = garment.get(field)
        if same(field, old, new):
            continue
        on = _empty(old) or (source in ("label", "tag") and field in LABEL_FIELDS)
        rows.append({"field": field, "old": old, "new": new, "source": source, "default_on": on})
    return rows
