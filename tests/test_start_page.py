"""Looks is the start page (0.4.2): first tab, the default view, and Today offers Add clothes."""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "wardrobe" / "app" / "static"


def test_tab_order(client):
    html = client.get("/").text
    nav = re.search(r'<nav class="tabs".*?</nav>', html, re.S).group(0)
    assert re.findall(r'data-tab="(\w+)"', nav) == ["looks", "wardrobe", "fit", "care", "shop"]
    assert re.findall(r'href="#/(\w+)"', nav) == ["looks", "wardrobe", "fit", "care", "shop"]


def test_empty_or_unknown_hash_opens_looks():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'const VIEWS = ["looks", "wardrobe", "fit", "care", "shop"];' in js
    body = re.search(r"function currentView\(\) \{(.*?)\n\}", js, re.S).group(1)
    assert 'VIEWS.includes(v) ? v : "looks"' in body


def test_add_button_only_on_wardrobe():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert '$("#fab").hidden = !(view === "wardrobe" && S.profileId);' in js


def test_today_without_a_look_offers_add_clothes():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    none = re.search(r'if \(t\.state === "none"\) return `(.*?)`;', js, re.S).group(1)
    assert "esc(t.reason)" in none
    assert '<a class="btn primary" href="#/wardrobe">Add clothes</a>' in none
