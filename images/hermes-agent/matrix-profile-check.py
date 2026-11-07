"""Build check for the matrix-profile plugin's Hermes-profile avatar mirror (Dockerfile).

Runs with HERMES_HOME set to a scratch directory. Gives the mirror a non-square JPEG and checks:
assets/avatar.png is a 256x256 PNG, ui_meta["hermes-bots"]["image"] is the same PNG as a data
URL, the existing ui_meta keys and other profile.yaml keys survive, and the key's revision goes up
by one on each call.
"""

import base64
import importlib.util
import io
import os
import sys
from pathlib import Path

sys.path.insert(0, "/opt/hermes")

from PIL import Image  # noqa: E402

import hermes_yaml  # noqa: E402

home = Path(os.environ["HERMES_HOME"])
(home / "profile.yaml").write_text(
    "display_name: Check\nui_meta:\n  hermes-bots:\n    screenAutoOpen: true\n_ui_meta_revisions:\n  hermes-bots: 3\n",
    encoding="utf-8",
)
(home / "assets").mkdir(exist_ok=True)
(home / "assets" / "avatar.jpg").write_bytes(b"stale")
src = home / "in.jpg"
Image.new("RGB", (640, 400), (200, 40, 40)).save(src, "JPEG")

spec = importlib.util.spec_from_file_location(
    "matrix_profile_check", "/opt/hermes-plugins/matrix-profile/__init__.py")
plugin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plugin)

for expected_revision in (4, 5):
    err = plugin._set_hermes_profile_avatar(src)
    assert err is None, err
    png = (home / "assets" / "avatar.png").read_bytes()
    with Image.open(io.BytesIO(png)) as out:
        assert out.format == "PNG" and out.size == (256, 256), (out.format, out.size)
    assert not (home / "assets" / "avatar.jpg").exists(), "stale avatar.jpg kept"
    meta = hermes_yaml.safe_load((home / "profile.yaml").read_text(encoding="utf-8"))
    bots = meta["ui_meta"]["hermes-bots"]
    assert bots["image"] == "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    assert bots["screenAutoOpen"] is True, bots
    assert meta["display_name"] == "Check", meta
    assert meta["_ui_meta_revisions"]["hermes-bots"] == expected_revision, meta["_ui_meta_revisions"]

print("matrix-profile avatar mirror ok")
