"""Shared vocabulary: categories, slots, patterns, occasions, measurement keys."""

CATEGORIES = {
    "top": {
        "label": "Tops",
        "sub": ["t-shirt", "shirt", "blouse", "polo", "tank", "long sleeve", "sweatshirt"],
    },
    "knitwear": {
        "label": "Knitwear",
        "sub": ["sweater", "cardigan", "hoodie", "vest", "turtleneck"],
    },
    "bottom": {
        "label": "Bottoms",
        "sub": ["jeans", "trousers", "chinos", "shorts", "skirt", "leggings"],
    },
    "dress": {
        "label": "Dresses",
        "sub": ["dress", "jumpsuit", "overall"],
    },
    "outerwear": {
        "label": "Outerwear",
        "sub": ["jacket", "coat", "blazer", "rain jacket", "puffer", "gilet", "trench"],
    },
    "shoes": {
        "label": "Shoes",
        "sub": ["sneakers", "boots", "loafers", "dress shoes", "heels", "flats", "sandals"],
    },
    "accessory": {
        "label": "Accessories",
        "sub": ["scarf", "belt", "hat", "bag", "gloves", "jewellery", "tie"],
    },
}

PATTERNS = ["solid", "stripe", "check", "print", "floral", "texture", "graphic"]
# Patterns that read as quiet and pair with anything else.
QUIET_PATTERNS = {"solid", "texture"}

OCCASIONS = ["casual", "work", "smart", "evening", "sport", "outdoor", "travel", "home"]
OCCASION_FORMALITY = {
    "home": 1, "sport": 1, "outdoor": 2, "casual": 2, "travel": 2,
    "work": 3, "smart": 4, "evening": 4,
}

SEASONS = ["spring", "summer", "autumn", "winter"]

STATUSES = ["active", "laundry", "repair", "stored", "archived"]
# A garment being added that hasn't been saved yet. Set by the server only; never a choice in the
# app, and left out of every list, suggestion and export.
DRAFT = "draft"

# item = the garment itself, label = care label, tag = brand or size tag, worn = someone wearing it.
PHOTO_KINDS = ["item", "label", "tag", "worn"]

FIT_TYPES = ["slim", "regular", "relaxed", "oversized"]

# Body measurements stored per profile (cm, except shoe size EU).
BODY_KEYS = {
    "height": "Height",
    "chest": "Chest / bust",
    "waist": "Waist",
    "hips": "Hips",
    "shoulder": "Shoulder width",
    "sleeve": "Arm length",
    "inseam": "Inseam",
    "neck": "Neck",
    "shoe_eu": "Shoe size (EU)",
}

# Garment measurements per category (cm, circumference = flat x 2).
GARMENT_KEYS = {
    "top": ["chest", "waist", "shoulder", "sleeve", "length"],
    "knitwear": ["chest", "shoulder", "sleeve", "length"],
    "outerwear": ["chest", "shoulder", "sleeve", "length"],
    "dress": ["chest", "waist", "hips", "length"],
    "bottom": ["waist", "hips", "inseam", "rise"],
    "shoes": ["shoe_eu"],
    "accessory": [],
}

FIT_AREAS = ["shoulders", "chest", "waist", "hips", "sleeves", "length", "rise"]
FIT_OVERALL = ["too_small", "slightly_small", "right", "slightly_big", "too_big"]
FIT_OVERALL_SCORE = {
    "too_small": -2, "slightly_small": -1, "right": 0, "slightly_big": 1, "too_big": 2,
}

CARE_FIELDS = {
    "wash": ["machine", "hand", "dry_clean", "spot", "no_wash"],
    "temp": [20, 30, 40, 60, 90],
    "cycle": ["normal", "delicate", "wool"],
    "bleach": ["any", "non_chlorine", "no"],
    "dry": ["tumble_normal", "tumble_low", "no_tumble", "line", "flat"],
    "iron": ["high", "medium", "low", "no"],
    "dry_clean": ["any", "P", "F", "no"],
}


def meta() -> dict:
    return {
        "categories": CATEGORIES,
        "patterns": PATTERNS,
        "occasions": OCCASIONS,
        "seasons": SEASONS,
        "statuses": STATUSES,
        "fit_types": FIT_TYPES,
        "body_keys": BODY_KEYS,
        "garment_keys": GARMENT_KEYS,
        "fit_areas": FIT_AREAS,
        "fit_overall": FIT_OVERALL,
        "care_fields": CARE_FIELDS,
    }
