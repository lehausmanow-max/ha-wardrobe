"""The photo buttons per platform (0.4.3): the Home Assistant Android app can't open the camera
from a page, so it gets one Add photos button; Chrome on Android and the Home Assistant iOS app
keep Camera and Gallery. The multi-pick gate for app versions up to 2026.10.1 stays as it is.

The rule lives in app.js, so the functions are cut out of it and run in Node."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

APP_JS = Path(__file__).resolve().parent.parent / "wardrobe" / "app" / "static" / "app.js"
NODE = shutil.which("node")

ANDROID_HA = ("Mozilla/5.0 (Linux; Android 16; SM-S938B; wv) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Version/4.0 Chrome/141.0.0.0 Mobile Safari/537.36 Home Assistant/{v} (Android 16; SM-S938B)")
UA = {
    "ha_android_2026.10.1": ANDROID_HA.format(v="2026.10.1-full"),
    "ha_android_2026.10.2": ANDROID_HA.format(v="2026.10.2-full"),
    "ha_android_no_version": ANDROID_HA.format(v="beta"),
    "chrome_android": ("Mozilla/5.0 (Linux; Android 16; SM-S938B) AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/141.0.0.0 Mobile Safari/537.36"),
    "ha_ios": ("Mozilla/5.0 (iPhone; CPU iPhone OS 19_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
               "Mobile/15E148 Home Assistant/2026.10.0 (io.robbie.HomeAssistant; build:2026.1234; iOS 19.0.0)"),
}


def _cut(src: str, name: str) -> str:
    """One top-level `function name(...) {...}` or `const name = ...;` from app.js."""
    m = re.search(rf"^function {name}\(.*?^\}}\n", src, re.S | re.M) or \
        re.search(rf"^const {name} = .*?;\n", src, re.S | re.M)
    assert m, f"{name} not found in app.js"
    return m.group(0)


@pytest.fixture(scope="module")
def results():
    if not NODE:
        pytest.skip("Node isn't installed")
    src = APP_JS.read_text(encoding="utf-8")
    code = "".join(_cut(src, n) for n in ("ICON_CAMERA", "ICON_GALLERY", "haAndroidAppVersion", "versionAtLeast",
                                          "haAppDropsMultiPick", "HA_APP_CAMERA_FROM", "haAppCanOpenCamera",
                                          "photoButtons"))
    code += f"""
const out = {{}};
for (const [k, ua] of Object.entries({json.dumps(UA)})) {{
  const html = photoButtons("btn", (src) => `data-pick="${{src}}"`, ua);
  out[k] = {{
    buttons: (html.match(/<button/g) || []).length,
    picks: [...html.matchAll(/data-pick="(\\w+)"/g)].map((m) => m[1]),
    labels: [...html.matchAll(/<\\/svg>([^<]+)<\\/button>/g)].map((m) => m[1]),
    camera: haAppCanOpenCamera(ua), dropsMulti: haAppDropsMultiPick(ua),
  }};
}}
console.log(JSON.stringify(out));
"""
    run = subprocess.run([NODE, "-e", code], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


@pytest.mark.parametrize("ua", ["ha_android_2026.10.1", "ha_android_2026.10.2", "ha_android_no_version"])
def test_home_assistant_android_app_gets_one_add_photos_button(results, ua):
    r = results[ua]
    assert r["camera"] is False
    assert r["buttons"] == 1 and r["picks"] == ["gallery"] and r["labels"] == ["Add photos"]


@pytest.mark.parametrize("ua", ["chrome_android", "ha_ios"])
def test_browsers_and_ios_app_keep_camera_and_gallery(results, ua):
    r = results[ua]
    assert r["camera"] is True
    assert r["buttons"] == 2 and r["picks"] == ["camera", "gallery"] and r["labels"] == ["Camera", "Gallery"]


def test_multi_pick_gate_unchanged(results):
    assert results["ha_android_2026.10.1"]["dropsMulti"] is True
    assert results["ha_android_no_version"]["dropsMulti"] is True
    assert results["ha_android_2026.10.2"]["dropsMulti"] is False
    assert results["chrome_android"]["dropsMulti"] is False
    assert results["ha_ios"]["dropsMulti"] is False


def test_camera_not_back_for_any_version_yet():
    # Set HA_APP_CAMERA_FROM to the first Android app release that opens the camera.
    assert "const HA_APP_CAMERA_FROM = null;" in APP_JS.read_text(encoding="utf-8")


def test_both_photo_places_use_the_rule():
    js = APP_JS.read_text(encoding="utf-8")
    assert 'photoButtons("btn", (src) => `data-pick="${src}"`)' in js  # new-garment photo strip
    assert 'photoButtons("btn ghost", (src) => `data-action="add-photos" data-id="${g.id}" data-src="${src}"`)' in js
    # No Camera button is rendered anywhere else.
    assert js.count('data-pick="camera"') == 0 and js.count('data-src="camera"') == 0
