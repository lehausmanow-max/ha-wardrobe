"""Fill a running dev instance with two demo profiles and drawn garment photos.

Usage: python3 dev/seed_demo.py http://127.0.0.1:8099
"""

import io
import json
import random
import sys
import urllib.request
import uuid

from PIL import Image, ImageDraw

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8099").rstrip("/")
random.seed(7)


def call(method, path, data=None):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(data).encode() if data is not None else None,
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def upload(path, fields, image_bytes):
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="p.jpg"\r\n'
                 f'Content-Type: image/jpeg\r\n\r\n'.encode() + image_bytes + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(BASE + path, data=b"".join(parts), method="POST",
                                 headers={"content-type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def shade(hx, f):
    r, g, b = (int(hx[i:i + 2], 16) for i in (1, 3, 5))
    return tuple(max(0, min(255, int(c * f))) for c in (r, g, b))


def draw(kind, color, pattern="solid", accent="#ffffff"):
    W, H = 600, 760
    bg = random.choice([(236, 234, 229), (229, 231, 233), (240, 238, 236)])
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    c = shade(color, 1)
    shapes = {
        "tee": [(170, 150), (250, 120), (350, 120), (430, 150), (520, 250), (450, 300), (420, 270),
                (420, 640), (180, 640), (180, 270), (150, 300), (80, 250)],
        "shirt": [(180, 140), (260, 110), (340, 110), (420, 140), (500, 400), (450, 420), (420, 300),
                  (420, 660), (180, 660), (180, 300), (150, 420), (100, 400)],
        "knit": [(170, 150), (250, 115), (350, 115), (430, 150), (510, 560), (450, 580), (420, 300),
                 (430, 640), (170, 640), (180, 300), (150, 580), (90, 560)],
        "trousers": [(200, 110), (400, 110), (440, 680), (330, 680), (300, 290), (270, 680), (160, 680)],
        "skirt": [(210, 160), (390, 160), (470, 600), (130, 600)],
        "dress": [(240, 100), (360, 100), (400, 300), (480, 690), (120, 690), (200, 300)],
        "coat": [(170, 130), (250, 100), (350, 100), (430, 130), (520, 600), (460, 620), (430, 320),
                 (440, 700), (160, 700), (170, 320), (140, 620), (80, 600)],
        "shoes": [(120, 470), (300, 450), (330, 380), (430, 380), (500, 470), (500, 540), (120, 540)],
        "boots": [(160, 240), (300, 240), (300, 450), (470, 470), (480, 560), (150, 560)],
    }
    poly = shapes[kind]
    d.polygon(poly, fill=c, outline=shade(color, 0.75))
    if pattern == "stripe":
        for y in range(120, 700, 28):
            d.line([(60, y), (540, y)], fill=accent, width=8)
        mask = Image.new("L", (W, H), 0)
        ImageDraw.Draw(mask).polygon(poly, fill=255)
        base = Image.new("RGB", (W, H), bg)
        base.paste(img, mask=mask)
        img = base
    elif pattern == "check":
        for x in range(60, 560, 40):
            d.line([(x, 80), (x, 720)], fill=accent, width=4)
        for y in range(80, 720, 40):
            d.line([(60, y), (540, y)], fill=accent, width=4)
        mask = Image.new("L", (W, H), 0)
        ImageDraw.Draw(mask).polygon(poly, fill=255)
        base = Image.new("RGB", (W, H), bg)
        base.paste(img, mask=mask)
        img = base
    if kind in ("shirt", "coat"):
        ImageDraw.Draw(img).line([(300, 130), (300, 660)], fill=shade(color, 0.8), width=3)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return buf.getvalue()


ALEX = [
    ("White Oxford shirt", "top", "shirt", "shirt", "#f3f3ef", "solid", 3, 2, "cotton", "Uniqlo", "M", 39.9),
    ("Light blue poplin shirt", "top", "shirt", "shirt", "#a9c4e0", "solid", 3, 2, "cotton", "COS", "M", 59),
    ("Navy striped tee", "top", "t-shirt", "tee", "#1f2a44", "stripe", 1, 2, "cotton", "Armor Lux", "M", 45),
    ("Grey marl tee", "top", "t-shirt", "tee", "#9a9b9d", "solid", 1, 2, "cotton", "Uniqlo", "M", 14.9),
    ("Black tee", "top", "t-shirt", "tee", "#1b1b1b", "solid", 1, 2, "cotton", "Uniqlo", "M", 14.9),
    ("Olive overshirt", "top", "shirt", "shirt", "#5d6136", "solid", 2, 3, "cotton twill", "Arket", "L", 89),
    ("Navy merino crewneck", "knitwear", "sweater", "knit", "#24304a", "solid", 3, 3, "merino wool", "Arket", "M", 79),
    ("Oatmeal cable knit", "knitwear", "sweater", "knit", "#d8ccb4", "texture", 2, 4, "wool", "Selected", "L", 99),
    ("Burgundy cardigan", "knitwear", "cardigan", "knit", "#6a1f2b", "solid", 3, 3, "lambswool", "Massimo Dutti", "M", 69),
    ("Dark indigo jeans", "bottom", "jeans", "trousers", "#2c3a57", "solid", 2, 3, "denim", "Levi's", "32/32", 110),
    ("Beige chinos", "bottom", "chinos", "trousers", "#c9b48d", "solid", 3, 2, "cotton", "Dockers", "32/32", 79),
    ("Charcoal wool trousers", "bottom", "trousers", "trousers", "#3a3b3e", "solid", 4, 3, "wool", "Suitsupply", "48", 129),
    ("White leather sneakers", "shoes", "sneakers", "shoes", "#f2f2ef", "solid", 2, 2, "leather", "Veja", "43", 140),
    ("Brown suede boots", "shoes", "boots", "boots", "#7a5236", "solid", 3, 3, "suede", "Clarks", "43", 160),
    ("Black derbies", "shoes", "dress shoes", "shoes", "#161616", "solid", 4, 2, "leather", "Loake", "9", 220),
    ("Navy rain jacket", "outerwear", "rain jacket", "coat", "#24304a", "solid", 2, 3, "nylon", "Rains", "M", 109),
    ("Camel wool coat", "outerwear", "coat", "coat", "#b0844f", "solid", 4, 4, "wool", "Suitsupply", "50", 349),
]

PARTNER = [
    ("Cream silk blouse", "top", "blouse", "shirt", "#efe9da", "solid", 4, 2, "silk", "& Other Stories", "36", 89),
    ("Breton top", "top", "long sleeve", "tee", "#f4f4f1", "stripe", 2, 2, "cotton", "Saint James", "S", 75),
    ("Black fitted tee", "top", "t-shirt", "tee", "#1a1a1a", "solid", 2, 2, "cotton", "COS", "S", 25),
    ("Sage linen shirt", "top", "shirt", "shirt", "#9fb099", "solid", 3, 1, "linen", "Arket", "36", 69),
    ("Grey cashmere sweater", "knitwear", "sweater", "knit", "#8a8b8d", "solid", 3, 3, "cashmere", "Uniqlo", "S", 99),
    ("Mustard cardigan", "knitwear", "cardigan", "knit", "#c99a2e", "solid", 2, 3, "wool", "Sezane", "S", 120),
    ("Wide-leg jeans", "bottom", "jeans", "trousers", "#4a6587", "solid", 2, 3, "denim", "Mango", "36", 49.9),
    ("Black tailored trousers", "bottom", "trousers", "trousers", "#1a1a1a", "solid", 4, 2, "polyester", "Zara", "36", 39.9),
    ("Pleated midi skirt", "bottom", "skirt", "skirt", "#6a1f2b", "solid", 3, 2, "polyester", "& Other Stories", "36", 69),
    ("Navy shirt dress", "dress", "dress", "dress", "#24304a", "solid", 3, 2, "cotton", "COS", "36", 89),
    ("Floral wrap dress", "dress", "dress", "dress", "#c0643f", "print", 3, 1, "viscose", "Mango", "S", 59.9),
    ("White sneakers", "shoes", "sneakers", "shoes", "#f2f2ef", "solid", 2, 2, "leather", "Adidas", "39", 110),
    ("Black ankle boots", "shoes", "boots", "boots", "#1c1c1c", "solid", 3, 3, "leather", "Vagabond", "39", 140),
    ("Trench coat", "outerwear", "trench", "coat", "#c9b48d", "solid", 3, 3, "cotton", "Mango", "S", 119),
    ("Grey check blazer", "outerwear", "blazer", "coat", "#7d7f84", "check", 4, 2, "wool", "Massimo Dutti", "36", 149),
]


def main():
    alex = call("POST", "/api/profiles", {"name": "Alex", "color": "#2b3a67"})
    partner = call("POST", "/api/profiles", {"name": "Partner", "color": "#8a3b4a"})
    call("PUT", f"/api/profiles/{alex['id']}", {"measurements": {
        "height": 182, "chest": 100, "waist": 86, "hips": 100, "shoulder": 46, "sleeve": 64,
        "inseam": 82, "shoe_eu": 43}, "style_notes": "Smart casual, mostly neutrals, likes navy and olive"})
    call("PUT", f"/api/profiles/{partner['id']}", {"measurements": {
        "height": 168, "chest": 88, "waist": 70, "hips": 96, "shoulder": 39, "sleeve": 58,
        "inseam": 77, "shoe_eu": 39}})

    made = {}
    for profile, items in ((alex, ALEX), (partner, PARTNER)):
        for name, cat, sub, shape, color, pattern, form, warmth, material, brand, size, price in items:
            g = call("POST", "/api/garments", {
                "profile_id": profile["id"], "name": name, "category": cat, "subcategory": sub,
                "pattern": pattern, "formality": form, "warmth": warmth, "material": material,
                "brand": brand, "size_label": size, "price": price,
                "seasons": [], "occasions": [], "fit_type": "regular"})
            accent = "#f4f4f1" if color != "#f4f4f1" else "#1f2a44"
            if name == "Breton top":
                color, accent = "#f4f4f1", "#1f2a44"
            upload(f"/api/garments/{g['id']}/photos", {"kind": "item"}, draw(shape, color, pattern, accent))
            made[name] = g["id"]

    # Measurements and fit logs to light up the Fit tab.
    call("PUT", f"/api/garments/{made['Navy merino crewneck']}", {"measurements": {"chest": 106, "shoulder": 46.5, "sleeve": 65, "length": 70}})
    call("PUT", f"/api/garments/{made['White Oxford shirt']}", {"measurements": {"chest": 112, "shoulder": 47, "sleeve": 66, "waist": 106}})
    call("PUT", f"/api/garments/{made['Charcoal wool trousers']}", {"measurements": {"waist": 84, "hips": 104, "inseam": 86}})
    call("PUT", f"/api/garments/{made['Camel wool coat']}", {"measurements": {"chest": 118, "shoulder": 47, "sleeve": 66}})
    call("PUT", f"/api/garments/{made['Dark indigo jeans']}", {"measurements": {"waist": 88, "hips": 104, "inseam": 81}})
    for name, overall, areas in [("Charcoal wool trousers", "slightly_small", {"waist": -1}),
                                 ("Navy merino crewneck", "right", {}),
                                 ("Beige chinos", "slightly_small", {"waist": -1, "hips": -1}),
                                 ("Light blue poplin shirt", "slightly_big", {"chest": 1})]:
        boundary = uuid.uuid4().hex
        fields = {"overall": overall, "areas": json.dumps(areas), "notes": ""}
        body = b"".join(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
                        for k, v in fields.items()) + f"--{boundary}--\r\n".encode()
        req = urllib.request.Request(BASE + f"/api/garments/{made[name]}/fit-log", data=body, method="POST",
                                     headers={"content-type": f"multipart/form-data; boundary={boundary}"})
        urllib.request.urlopen(req).read()

    # Some wear history and a laundry basket.
    for name in ("Grey marl tee", "Dark indigo jeans", "White leather sneakers", "Navy rain jacket"):
        call("POST", f"/api/garments/{made[name]}/wear", {})
    for name in ("Black tee", "Light blue poplin shirt", "Navy merino crewneck", "White Oxford shirt"):
        call("PUT", f"/api/garments/{made[name]}", {"status": "laundry"})
    call("POST", "/api/looks", {"profile_id": alex["id"], "name": "Office, rainy day", "occasion": "work",
                                "garment_ids": [made["Light blue poplin shirt"], made["Charcoal wool trousers"],
                                                made["Brown suede boots"], made["Navy rain jacket"]], "rating": 4})
    call("POST", "/api/wishlist", {"profile_id": alex["id"], "title": "Grey flannel trousers", "category": "bottom",
                                   "reason": "Second smart bottom for work", "priority": 1})
    print("Seeded", len(made), "garments")


if __name__ == "__main__":
    main()
