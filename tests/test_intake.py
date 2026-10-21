"""One-pass intake: drafts, the combined photo read, label precedence, re-read proposals, photo kinds."""

import io
import json
import sqlite3

import pytest
from PIL import Image

from wardrobe import ai, config, intake, main


# ------------------------------------------------------------------ helpers

def jpeg(rgb=(40, 60, 120), size=(400, 500)) -> bytes:
    img = Image.new("RGB", size, (235, 235, 232))
    w, h = size
    img.paste(Image.new("RGB", (w // 2, h // 2), rgb), (w // 4, h // 4))
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    return buf.getvalue()


def files(rgb=(40, 60, 120)):
    return {"file": ("p.jpg", jpeg(rgb), "image/jpeg")}


class FakeVision:
    """Stands in for Claude or Ollama: returns canned JSON and records what it was sent."""

    def __init__(self, reply, name="claude"):
        self.reply, self.name, self.calls = reply, name, []

    def ask(self, prompt, images=None, want_json=False, system=None, **kw):
        self.calls.append({"prompt": prompt, "images": list(images or []), **kw})
        reply = self.reply(prompt) if callable(self.reply) else self.reply
        if isinstance(reply, Exception):
            raise reply
        return json.dumps(reply)


@pytest.fixture
def use_vision(monkeypatch):
    def install(reply, name="claude"):
        fake = FakeVision(reply, name)
        monkeypatch.setattr(main, "provider", lambda kind: fake if kind == "vision" else None)
        return fake
    return install


def new_draft(client, profile, n_photos=1):
    r = client.post("/api/intake", data={"profile_id": profile["id"]}, files=files())
    assert r.status_code == 201, r.text
    g = r.json()
    for i in range(n_photos - 1):
        r = client.post(f"/api/garments/{g['id']}/photos", data={"kind": "item"}, files=files((90 + i, 20, 20)))
        assert r.status_code == 201, r.text
        g = r.json()
    return g


def photo_ids(g):
    return [p["id"] for p in sorted(g["photos"], key=lambda p: p["id"])]


CARE_WOOL = {"wash": "machine", "temp": 30, "cycle": "wool", "bleach": "no", "dry": "flat",
             "iron": "low", "dry_clean": "P", "notes": "Wash inside out"}


def full_reply(**labels):
    """Four photos: front, back, care label, brand tag."""
    lab = {"brand": "Realbrand", "size_label": "M", "composition": "80% Wool, 20% Polyamide",
           "care": CARE_WOOL} | labels
    return {
        "photos": [{"photo": 1, "role": "front"}, {"photo": 2, "role": "back"},
                   {"photo": 3, "role": "care_label"}, {"photo": 4, "role": "brand_tag"}],
        "garment": {"name": "Navy crewneck", "category": "knitwear", "subcategory": "sweater",
                    "colors": ["#1f2a44"], "pattern": "solid", "material": "cotton", "formality": 3,
                    "warmth": 4, "seasons": ["autumn", "winter"], "occasions": ["casual"],
                    "logo_brand": "Logoco"},
        "labels": lab,
        "confidence": {"garment": "high", "labels": "high"},
    }


# ------------------------------------------------------------------ drafts

def test_intake_starts_a_draft_without_ai(client, profile, use_vision):
    fake = use_vision(full_reply())
    g = new_draft(client, profile)
    assert g["status"] == "draft"
    assert g["colors"], "local colours come from the first photo"
    assert fake.calls == [], "nothing is read until all photos are in"

    listed = client.get("/api/garments", params={"profile_id": profile["id"]}).json()
    assert g["id"] not in [x["id"] for x in listed]
    drafts = client.get("/api/garments", params={"profile_id": profile["id"], "status": "draft"}).json()
    assert [x["id"] for x in drafts] == [g["id"]]


def test_saving_a_draft_makes_it_a_garment(client, profile):
    g = new_draft(client, profile)
    r = client.put(f"/api/garments/{g['id']}", json={"name": "Blue tee", "status": "active"})
    assert r.status_code == 200 and r.json()["status"] == "active"
    listed = client.get("/api/garments", params={"profile_id": profile["id"]}).json()
    assert [x["id"] for x in listed] == [g["id"]]


def test_draft_status_cannot_be_set_by_the_app(client, profile):
    r = client.post("/api/garments", json={"profile_id": profile["id"], "name": "Tee", "category": "top"})
    r = client.put(f"/api/garments/{r.json()['id']}", json={"status": "draft"})
    assert r.status_code == 400


def test_drafts_older_than_a_day_are_deleted(client, profile):
    old = new_draft(client, profile)
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("UPDATE garments SET created_at = datetime('now', '-2 days') WHERE id = ?", (old["id"],))
    conn.commit()
    conn.close()
    drafts = client.get("/api/garments", params={"profile_id": profile["id"], "status": "draft"}).json()
    assert drafts == [], "an expired draft isn't offered to continue"

    photo = config.MEDIA_DIR / old["photos"][0]["filename"]
    assert photo.exists()
    new = new_draft(client, profile)  # the next intake clears it out
    assert not photo.exists()
    conn = sqlite3.connect(config.DB_PATH)
    rows = conn.execute("SELECT g.id, p.filename FROM garments g JOIN photos p ON p.garment_id = g.id").fetchall()
    conn.close()
    # SQLite may hand the freed id to the new draft, so check by photo.
    assert rows == [(new["id"], new["photos"][0]["filename"])]


def test_drafts_are_left_out_everywhere(client, profile):
    pid = profile["id"]
    for name, cat, sub, colour in (("White tee", "top", "t-shirt", "#f2f2f2"), ("Jeans", "bottom", "jeans", "#2b3a55"),
                                   ("Sneakers", "shoes", "sneakers", "#ffffff")):
        r = client.post("/api/garments", json={"profile_id": pid, "name": name, "category": cat,
                                               "subcategory": sub, "colors": [colour]})
        assert r.status_code == 201
    draft = new_draft(client, profile)
    client.put(f"/api/garments/{draft['id']}", json={"category": "top", "subcategory": "t-shirt",
                                                     "colors": ["#202020"]})
    did = draft["id"]

    for status in (None, "current"):
        params = {"profile_id": pid} | ({"status": status} if status else {})
        assert did not in [g["id"] for g in client.get("/api/garments", params=params).json()]

    looks = client.post("/api/suggest", json={"profile_id": pid, "occasion": "casual", "use_weather": False}).json()
    assert looks["looks"], "the three saved garments make a look"
    assert all(did not in [g["id"] for g in lk["items"]] for lk in looks["looks"])

    shop = client.get("/api/shopping", params={"profile_id": pid}).json()
    assert did not in [g["id"] for g in shop["hard_to_style"] + shop["underused"]]
    assert shop["counts"]["top"] == 1

    fit = client.get("/api/fit/overview", params={"profile_id": pid}).json()
    assert did not in [f["id"] for f in fit["flagged"]]

    laundry = client.get("/api/laundry").json()
    assert did not in [g["id"] for load in laundry["loads"] for g in load["items"]] + [g["id"] for g in laundry["due"]]

    export = client.get("/api/export").json()
    assert did not in [g["id"] for g in export["garments"]]
    assert did not in [p["garment_id"] for p in export["photos"]]
    assert len(export["garments"]) == 3


# ------------------------------------------------------------------ reading a draft

def test_read_fills_in_a_draft_and_labels_win(client, profile, use_vision):
    fake = use_vision(full_reply())
    g = new_draft(client, profile, n_photos=4)
    ids = photo_ids(g)
    r = client.post(f"/api/garments/{g['id']}/read", json={})
    assert r.status_code == 200, r.text
    out = r.json()
    got = out["garment"]

    assert len(fake.calls) == 1 and len(fake.calls[0]["images"]) == 4, "one call with all photos"
    assert got["status"] == "draft", "still a draft until the owner saves"
    assert got["name"] == "Navy crewneck" and got["category"] == "knitwear"
    # Labels and tags beat the photo.
    assert got["material"] == "80% wool, 20% polyamide"
    assert got["brand"] == "Realbrand"
    assert got["size_label"] == "M"
    c = got["care"]
    assert (c["wash"], c["temp"], c["cycle"], c["dry"], c["iron"], c["dry_clean"]) == \
        ("machine", 30, "wool", "flat", "low", "P")
    assert c["bleach"] == "no" and c["bleach_from_label"] is True
    assert c["notes"] == "Wash inside out"
    assert c["wash_after"] == 6, "wool knitwear default"

    src = out["read"]["sources"]
    assert (src["material"], src["care"], src["brand"], src["size_label"], src["name"]) == \
        ("label", "label", "tag", "tag", "photo")
    kinds = {p["id"]: p["kind"] for p in got["photos"]}
    assert [kinds[i] for i in ids] == ["item", "item", "label", "tag"]
    primary = [p["id"] for p in got["photos"] if p["is_primary"]]
    assert primary == [ids[0]], "the front is the main photo"


def test_photo_guesses_fill_in_when_there_is_no_label(client, profile, use_vision):
    reply = full_reply()
    reply["labels"] = {}
    reply["photos"] = [{"photo": 1, "role": "front"}]
    use_vision(reply)
    g = new_draft(client, profile)
    got = client.post(f"/api/garments/{g['id']}/read", json={}).json()
    assert got["garment"]["material"] == "cotton"
    assert got["garment"]["brand"] == "Logoco", "a logo on the garment is the fallback"
    assert got["garment"]["size_label"] == "", "size never comes from the garment photo"
    assert "size_label" not in got["read"]["sources"]
    assert got["read"]["sources"]["care"] == "defaults"
    assert "bleach" not in got["garment"]["care"], "fibre defaults never set bleach"


def test_brand_on_a_care_label_counts_as_label(client, profile, use_vision):
    reply = full_reply()
    reply["photos"] = [{"photo": 1, "role": "front"}, {"photo": 2, "role": "care_label"}]
    use_vision(reply)
    g = new_draft(client, profile, n_photos=2)
    src = client.post(f"/api/garments/{g['id']}/read", json={}).json()["read"]["sources"]
    assert src["brand"] == "label" and src["material"] == "label"


def test_kinds_the_owner_set_are_kept(client, profile, use_vision):
    fake = use_vision(full_reply())
    g = new_draft(client, profile, n_photos=4)
    ids = photo_ids(g)
    client.patch(f"/api/photos/{ids[2]}", json={"kind": "item"})  # owner says: not a label
    out = client.post(f"/api/garments/{g['id']}/read", json={"keep": [ids[2]]}).json()
    kinds = {p["id"]: p["kind"] for p in out["garment"]["photos"]}
    assert kinds[ids[2]] == "item"
    assert "the owner said so" in fake.calls[0]["prompt"]


# ------------------------------------------------------------------ re-reading a saved garment

def saved_garment(client, profile, **extra):
    data = {"profile_id": profile["id"], "name": "My jumper", "category": "knitwear", "subcategory": "sweater",
            "brand": "Typed brand", "material": "cotton", "colors": ["#1f2a44"]} | extra
    g = client.post("/api/garments", json=data).json()
    for i in range(4):
        g = client.post(f"/api/garments/{g['id']}/photos", data={"kind": "item"}, files=files((20 + i, 30, 90))).json()
    return g


def test_reread_proposes_and_writes_nothing_but_photo_kinds(client, profile, use_vision):
    use_vision(full_reply())
    g = saved_garment(client, profile)
    before = client.get(f"/api/garments/{g['id']}").json()
    out = client.post(f"/api/garments/{g['id']}/read", json={}).json()

    rows = {p["field"]: p for p in out["proposals"]}
    assert rows["brand"]["new"] == "Realbrand" and rows["brand"]["old"] == "Typed brand"
    assert rows["brand"]["default_on"] is True, "a brand read from a tag is ticked"
    assert rows["material"]["default_on"] is True and rows["material"]["source"] == "label"
    assert rows["care"]["default_on"] is True
    assert rows["size_label"]["default_on"] is True, "empty before"
    assert rows["name"]["default_on"] is False, "a name the owner typed is not ticked"
    assert "subcategory" not in rows and "colors" not in rows, "unchanged fields aren't proposed"

    after = client.get(f"/api/garments/{g['id']}").json()
    for k in ("name", "brand", "material", "size_label", "care"):
        assert after[k] == before[k]
    assert sorted(p["kind"] for p in after["photos"]) == ["item", "item", "label", "tag"]
    assert [p["id"] for p in after["photos"] if p["is_primary"]] == \
        [p["id"] for p in before["photos"] if p["is_primary"]], "main photo unchanged on a saved garment"

    r = client.post(f"/api/garments/{g['id']}/read/apply",
                    json={"values": {"brand": rows["brand"]["new"], "material": rows["material"]["new"]}})
    assert r.status_code == 200
    got = r.json()
    assert got["brand"] == "Realbrand" and got["material"] == "80% wool, 20% polyamide"
    assert got["name"] == "My jumper", "unticked fields stay"
    assert got["care"] == before["care"]


def test_apply_needs_values(client, profile):
    g = saved_garment(client, profile)
    assert client.post(f"/api/garments/{g['id']}/read/apply", json={"values": {}}).status_code == 400
    assert client.post(f"/api/garments/{g['id']}/read/apply", json={"values": {"price": 3}}).status_code == 400


def test_bleach_only_from_labels_and_cleared_by_a_later_label(client, profile, use_vision):
    use_vision(full_reply())
    g = saved_garment(client, profile)
    out = client.post(f"/api/garments/{g['id']}/read", json={}).json()
    care = next(p for p in out["proposals"] if p["field"] == "care")["new"]

    # Sent without the label flag, bleach is dropped: it can't be set by hand.
    got = client.post(f"/api/garments/{g['id']}/read/apply", json={"values": {"care": care}}).json()
    assert "bleach" not in got["care"]

    got = client.post(f"/api/garments/{g['id']}/read/apply",
                      json={"values": {"care": care}, "care_from_label": True}).json()
    assert got["care"]["bleach"] == "no"

    # An ordinary save keeps the label's bleach and can't change it.
    got = client.put(f"/api/garments/{g['id']}", json={"care": got["care"] | {"bleach": "any"}}).json()
    assert got["care"]["bleach"] == "no"

    # A new label read without a bleach symbol clears it.
    no_bleach = {k: v for k, v in CARE_WOOL.items() if k != "bleach"}
    use_vision(full_reply(care=no_bleach))
    out = client.post(f"/api/garments/{g['id']}/read", json={}).json()
    row = next(p for p in out["proposals"] if p["field"] == "care")
    assert row["default_on"] is True and "bleach" not in row["new"]
    got = client.post(f"/api/garments/{g['id']}/read/apply",
                      json={"values": {"care": row["new"]}, "care_from_label": True}).json()
    assert "bleach" not in got["care"]


# ------------------------------------------------------------------ which photos are sent

def test_at_most_six_photos_main_first_never_worn(client, profile, use_vision):
    fake = use_vision({"photos": [], "garment": {}, "labels": {}})
    g = saved_garment(client, profile)  # 4 item photos
    gid = g["id"]
    for kind in ("worn", "item", "item", "label"):
        g = client.post(f"/api/garments/{gid}/photos", data={"kind": kind}, files=files()).json()
    chosen = intake.pick_photos(g["photos"])
    assert len(chosen) == 6
    assert chosen[0]["is_primary"] and chosen[1]["kind"] == "label"
    assert all(p["kind"] != "worn" for p in chosen)

    client.post(f"/api/garments/{gid}/read", json={})
    assert len(fake.calls[0]["images"]) == 6


def test_reading_needs_vision_and_a_photo(client, profile, use_vision):
    g = client.post("/api/garments", json={"profile_id": profile["id"], "name": "Tee", "category": "top"}).json()
    assert client.post(f"/api/garments/{g['id']}/read", json={}).status_code == 400  # no vision provider
    use_vision(full_reply())
    assert client.post(f"/api/garments/{g['id']}/read", json={}).status_code == 400  # no photo


def test_ai_failure_is_reported(client, profile, use_vision):
    use_vision(ai.AIError("overloaded"))
    g = new_draft(client, profile)
    r = client.post(f"/api/garments/{g['id']}/read", json={})
    assert r.status_code == 502 and "overloaded" in r.json()["error"]


def test_ollama_reads_photo_by_photo(client, profile, use_vision):
    def reply(prompt):
        if "care label" in prompt:
            return {"composition": "100% cotton", **{k: v for k, v in CARE_WOOL.items() if k != "bleach"},
                    "confidence": "high"}
        return {"name": "Grey tee", "category": "top", "subcategory": "t-shirt", "colors": ["#888888"],
                "brand": ""}
    fake = use_vision(reply, name="ollama")
    g = new_draft(client, profile, n_photos=2)
    ids = photo_ids(g)
    client.patch(f"/api/photos/{ids[1]}", json={"kind": "label"})
    out = client.post(f"/api/garments/{g['id']}/read", json={}).json()
    assert [len(c["images"]) for c in fake.calls] == [1, 1]
    assert out["garment"]["name"] == "Grey tee" and out["garment"]["material"] == "100% cotton"
    assert out["read"]["sources"]["care"] == "label"
    assert sorted(p["kind"] for p in out["garment"]["photos"]) == ["item", "label"]


# ------------------------------------------------------------------ photos and prices

def test_main_photo_moves_when_its_kind_changes(client, profile):
    g = new_draft(client, profile, n_photos=2)
    first, second = photo_ids(g)
    g = client.patch(f"/api/photos/{first}", json={"kind": "label"}).json()
    assert [p["id"] for p in g["photos"] if p["is_primary"]] == [second]
    g = client.post(f"/api/photos/{first}").json()  # make main: becomes a garment photo again
    kinds = {p["id"]: (p["kind"], p["is_primary"]) for p in g["photos"]}
    assert kinds[first] == ("item", 1) and kinds[second] == ("item", 0)
    assert client.patch(f"/api/photos/{first}", json={"kind": "selfie"}).status_code == 400
    g = client.delete(f"/api/photos/{first}").json()
    assert [p["id"] for p in g["photos"] if p["is_primary"]] == [second]


def test_hidden_price_survives_a_save(client, profile):
    g = client.post("/api/garments", json={"profile_id": profile["id"], "name": "Coat", "category": "outerwear",
                                           "price": 149.95, "purchase_date": "2025-11-02"}).json()
    got = client.put(f"/api/garments/{g['id']}", json={"name": "Wool coat", "notes": "Dry clean"}).json()
    assert got["price"] == 149.95 and got["purchase_date"] == "2025-11-02"
    export = client.get("/api/export").json()
    assert export["garments"][0]["price"] == 149.95
