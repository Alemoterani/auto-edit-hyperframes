"""Tests for `--graphics` on shorts: pipeline flag + overlayer filter."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from auto_edit import pipeline as pl
from tools.overlayer import SHORT_TEMPLATES, _filter_for_short


def _init(tmp_path, video_type):
    ws = tmp_path / "ws"
    ws.mkdir()
    video = tmp_path / "v.mp4"
    video.write_text("")
    pl.init(ws, video, video_type, "ctx")
    return ws


def test_graphics_turns_overlay_on_for_short(tmp_path):
    ws = _init(tmp_path, "short")
    assert pl.load(ws)["stages"]["overlay"]["status"] == "skip"
    pl.set_graphics(ws)
    p = pl.load(ws)
    assert p["graphics"] is True
    assert p["stages"]["overlay"]["status"] == "pending"


def test_graphics_does_not_reset_a_finished_overlay(tmp_path):
    ws = _init(tmp_path, "long")
    p = pl.load(ws)
    p["stages"]["overlay"] = {"status": "complete"}
    pl.save(ws, p)
    pl.set_graphics(ws)
    assert pl.load(ws)["stages"]["overlay"]["status"] == "complete"


def test_short_keeps_only_explainer_templates():
    overlays = [
        {"template": "stat", "original_start": 1},
        {"template": "lower_third", "original_start": 2},
        {"file": "ctas.mp4", "original_start": 3},
        {"template": "steps", "original_start": 4},
    ]
    kept, dropped = _filter_for_short(overlays, "short")
    assert [o["template"] for o in kept] == ["stat", "steps"]
    assert dropped == ["template:lower_third", "ctas.mp4"]


def test_long_keeps_everything():
    overlays = [{"template": "lower_third", "original_start": 2}, {"file": "ctas.mp4", "original_start": 3}]
    assert _filter_for_short(overlays, "long") == (overlays, [])


def test_short_templates_exist():
    from auto_edit import hyperframes
    for name in SHORT_TEMPLATES:
        assert (hyperframes.template_dir(name) / "index.html").is_file()
