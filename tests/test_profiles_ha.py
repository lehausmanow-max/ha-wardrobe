"""Profiles follow the Home Assistant user ID: name match once, then the ID decides; Unlink."""


def headers(uid="", name="", display=""):
    return {"X-Remote-User-Id": uid, "X-Remote-User-Name": name, "X-Remote-User-Display-Name": display}


def new_profile(client, name, ha_user=""):
    r = client.post("/api/profiles", json={"name": name, "ha_user": ha_user})
    assert r.status_code == 201, r.text
    return r.json()


def meta(client, **kw):
    r = client.get("/api/meta", headers=headers(**kw))
    assert r.status_code == 200, r.text
    return r.json()


def by_id(data, pid):
    return next(p for p in data["profiles"] if p["id"] == pid)


def test_name_match_binds_once_then_id_decides(client):
    sam = new_profile(client, "Sam")
    robin = new_profile(client, "Robin", ha_user="rob")

    data = meta(client, uid="u-sam", name="sammy", display="Sam")
    assert data["matched_profile"] == sam["id"]
    p = by_id(data, sam["id"])
    assert p["ha_user_id"] == "u-sam"
    assert p["settings"]["ha_display_name"] == "Sam"

    # Renamed in Home Assistant: the ID still finds the profile.
    assert meta(client, uid="u-sam", name="s", display="Someone else")["matched_profile"] == sam["id"]

    # Username match binds the other profile.
    assert meta(client, uid="u-rob", name="rob", display="R")["matched_profile"] == robin["id"]
    assert by_id(meta(client), robin["id"])["ha_user_id"] == "u-rob"


def test_bound_profile_is_not_taken_by_another_user(client):
    sam = new_profile(client, "Sam")
    meta(client, uid="u-sam", display="Sam")
    data = meta(client, uid="u-other", display="Sam")
    assert data["matched_profile"] is None
    assert by_id(data, sam["id"])["ha_user_id"] == "u-sam"


def test_no_id_header_matches_by_name_without_binding(client):
    sam = new_profile(client, "Sam")
    data = meta(client, display="Sam")
    assert data["matched_profile"] == sam["id"]
    assert by_id(data, sam["id"])["ha_user_id"] == ""


def test_unlink(client):
    sam = new_profile(client, "Sam")
    meta(client, uid="u-sam", display="Sam")
    r = client.put(f"/api/profiles/{sam['id']}", json={"unlink_ha": True})
    assert r.status_code == 200
    assert r.json()["ha_user_id"] == "" and "ha_display_name" not in r.json()["settings"]
    # Opening the app again links it again.
    assert by_id(meta(client, uid="u-sam", display="Sam"), sam["id"])["ha_user_id"] == "u-sam"


def test_id_cannot_be_set_from_the_app(client):
    sam = new_profile(client, "Sam")
    r = client.put(f"/api/profiles/{sam['id']}", json={"ha_user_id": "u-evil"})
    assert r.json()["ha_user_id"] == ""


def test_meta_reports_bridge_off_outside_ha(client):
    data = meta(client)
    assert data["running_in_ha"] is False
    assert data["ha_bridge"] == {"enabled": False, "connected": False, "since": None, "last_error": None}
