"""Tests for tools/overlayer.py.

Two concerns:

1. Frame-rate handling in the FFmpeg command. Regression: the concat'd edit is
   slightly VFR, so `overlay` resolved the output to a doubled timebase (59.94
   for a 29.97 edit) and the encoder emitted every frame as if it belonged there
   — video played at 2x while audio stayed put.
2. Overlay resolution and the missing-asset gate: which planned overlays are
   found / missing / removed-by-cut, and whether a missing .mp4 is skipped with
   a warning (default) or fails the stage (AUTO_EDIT_OVERLAYS_STRICT=1).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools import overlayer
from tools.overlayer import (
    _resolve_overlays,
    _check_assets_present,
    _missing_assets_message,
)
from auto_edit.overlay_assets import overlay_search_dirs


# ── Frame-rate handling (2x/slow-motion regression) ──────────────────────────

def _capture_cmd(monkeypatch, fps="30000/1001", has_audio=True, asset=Path("cta.mp4")):
    """Run _run_ffmpeg_overlay with FFmpeg stubbed; return the argv it built."""
    captured = {}

    class Result:
        returncode = 0

    monkeypatch.setattr(overlayer, "_video_size", lambda p: (3840, 2160))
    monkeypatch.setattr(overlayer, "_video_fps", lambda p: fps)
    monkeypatch.setattr(overlayer, "_has_audio_stream", lambda p: has_audio)
    monkeypatch.setattr(overlayer, "_get_video_codec", lambda: ("libx264", ["-crf", "23"]))
    def fake_run(cmd, *args, **kwargs):
        captured["cmd"] = cmd
        return Result()

    monkeypatch.setattr(overlayer.subprocess, "run", fake_run)

    overlayer._run_ffmpeg_overlay(
        Path("edit.mp4"),
        [{"asset": asset, "start": 2.0, "end": 8.0}],
        Path("out.mp4"),
    )
    return captured["cmd"]


def test_output_is_pinned_to_the_edit_frame_rate(monkeypatch):
    cmd = _capture_cmd(monkeypatch)

    assert "-r" in cmd
    assert cmd[cmd.index("-r") + 1] == "30000/1001"
    assert "-fps_mode" in cmd and cmd[cmd.index("-fps_mode") + 1] == "cfr"


def test_both_streams_are_normalized_before_overlay(monkeypatch):
    cmd = _capture_cmd(monkeypatch)
    filters = cmd[cmd.index("-filter_complex") + 1]

    assert "[0:v]fps=30000/1001[base]" in filters  # main video
    assert "[1:v]setpts=PTS-STARTPTS+2.000/TB,fps=30000/1001,scale=" in filters  # overlay asset
    assert "[base][ck0]overlay=" in filters


def test_unknown_frame_rate_falls_back_to_previous_behaviour(monkeypatch):
    """Never block the render because ffprobe could not report a frame rate."""
    cmd = _capture_cmd(monkeypatch, fps=None)
    filters = cmd[cmd.index("-filter_complex") + 1]

    assert "-r" not in cmd
    assert "fps=" not in filters
    assert "[0:v][ck0]overlay=" in filters


def test_audio_is_copied_untouched(monkeypatch):
    cmd = _capture_cmd(monkeypatch)

    assert cmd[cmd.index("-c:a") + 1] == "copy"


def test_video_without_audio_maps_no_audio(monkeypatch):
    cmd = _capture_cmd(monkeypatch, has_audio=False)

    assert "-c:a" not in cmd


# ── Overlay resolution + missing-asset gate ──────────────────────────────────

KEPT = [(0.0, 10.0), (20.0, 30.0)]  # 10-20s is cut


class TestResolveOverlays:
    def test_found_missing_and_removed_are_split(self, tmp_path):
        (tmp_path / "ctas.mp4").write_bytes(b"x")  # asset present
        overlays = [
            {"file": "ctas.mp4", "original_start": 5.0},    # kept → found
            {"file": "gone.mp4", "original_start": 5.0},    # asset absent → missing
            {"file": "ctas.mp4", "original_start": 15.0},   # inside a cut → removed
        ]
        found, missing, removed = _resolve_overlays(overlays, [tmp_path], KEPT)

        assert missing == ["gone.mp4"]
        assert removed == ["ctas.mp4"]
        assert len(found) == 1
        ov, asset, post_cut_start = found[0]
        assert asset == tmp_path / "ctas.mp4"
        assert post_cut_start == pytest.approx(5.0)

    def test_timestamp_after_cut_remaps_to_compacted_timeline(self, tmp_path):
        (tmp_path / "ctas.mp4").write_bytes(b"x")
        overlays = [{"file": "ctas.mp4", "original_start": 25.0}]
        found, missing, removed = _resolve_overlays(overlays, [tmp_path], KEPT)
        assert not missing and not removed
        # 25s sits in the second kept block; first block (10s) is prepended.
        assert found[0][2] == pytest.approx(15.0)

    def test_all_found(self, tmp_path):
        (tmp_path / "a.mp4").write_bytes(b"x")
        overlays = [{"file": "a.mp4", "original_start": 1.0}]
        found, missing, removed = _resolve_overlays(overlays, [tmp_path], KEPT)
        assert len(found) == 1 and not missing and not removed


class TestCheckAssetsPresent:
    def test_no_missing_is_noop(self, capsys):
        _check_assets_present([], [Path("/nowhere")])
        assert capsys.readouterr().out == ""

    def test_missing_only_warns_by_default(self, monkeypatch, capsys):
        """Overlays live outside the repo, so a fresh install has none — the
        edit must still ship instead of dying at the overlay stage."""
        monkeypatch.delenv("AUTO_EDIT_OVERLAYS_STRICT", raising=False)
        _check_assets_present(["ctas.mp4"], [Path("/opt/overlays")])  # must not raise
        out = capsys.readouterr().out
        assert "WARNING" in out
        assert "ctas.mp4" in out

    def test_strict_env_turns_it_into_a_failure(self, monkeypatch):
        monkeypatch.setenv("AUTO_EDIT_OVERLAYS_STRICT", "1")
        with pytest.raises(FileNotFoundError, match="not found"):
            _check_assets_present(["ctas.mp4"], [Path("/opt/overlays")])

    def test_message_points_at_the_env_var(self):
        msg = _missing_assets_message(["ctas.mp4"], [Path("/opt/overlays")])
        assert "ctas.mp4" in msg
        assert "AUTO_EDIT_ASSETS_OVERLAYS" in msg


class TestOverlaySearchDirs:
    def test_env_override_wins(self, monkeypatch, tmp_path):
        monkeypatch.setenv("AUTO_EDIT_ASSETS_OVERLAYS", str(tmp_path))
        dirs = overlay_search_dirs(Path("/some/repo"))
        assert dirs == [tmp_path.resolve()]

    def test_default_is_assets_then_mirror(self, monkeypatch):
        monkeypatch.delenv("AUTO_EDIT_ASSETS_OVERLAYS", raising=False)
        repo = Path("/some/repo")
        dirs = overlay_search_dirs(repo)
        # overlay_search_dirs resolves the root (adds the drive on Windows).
        root = repo.resolve()
        assert dirs == [root / "assets" / "overlays", root / "overlays"]


# ── HyperFrames templates (alpha .mov, rendered on demand) ───────────────────

class TestTemplateOverlays:
    def test_template_is_rendered_and_placed(self, tmp_path):
        rendered = tmp_path / "lower_third.mov"
        calls = []
        def render(ov):
            calls.append(ov)
            return rendered
        overlays = [{"template": "lower_third", "vars": {"title": "Oi"}, "original_start": 25.0}]
        found, missing, removed = _resolve_overlays(overlays, [tmp_path], KEPT, render)
        assert not missing and not removed
        assert found[0][1] == rendered and found[0][2] == pytest.approx(15.0)
        assert calls == overlays

    def test_template_inside_a_cut_is_not_rendered(self, tmp_path):
        def render(ov):
            raise AssertionError("must not render a removed overlay")
        overlays = [{"template": "cta", "original_start": 15.0}]
        found, missing, removed = _resolve_overlays(overlays, [tmp_path], KEPT, render)
        assert removed == ["template:cta"] and not found

    def test_failed_render_counts_as_missing(self, tmp_path):
        def render(ov):
            raise RuntimeError("npx not found")
        overlays = [{"template": "cta", "original_start": 5.0}]
        found, missing, removed = _resolve_overlays(overlays, [tmp_path], KEPT, render)
        assert missing == ["template:cta"] and not found


def test_alpha_asset_skips_chromakey(monkeypatch):
    graph = " ".join(_capture_cmd(monkeypatch, asset=Path("hf_cache/cta-abc.mov")))
    assert "chromakey" not in graph
    assert "format=yuva420p" in graph


def test_green_screen_mp4_still_uses_chromakey(monkeypatch):
    graph = " ".join(_capture_cmd(monkeypatch))
    assert "chromakey" in graph


def test_overlay_starts_playing_at_its_placement(monkeypatch):
    # Without the PTS shift the overlay plays from t=0 and is already over
    # (frozen on its last frame) by the time `enable` turns it on at 2s.
    graph = " ".join(_capture_cmd(monkeypatch))
    assert "setpts=PTS-STARTPTS+2.000/TB" in graph


def test_video_filter_runs_before_the_overlays(monkeypatch):
    # The graphics are rendered at the post-filter size, so the base video must be
    # filtered (e.g. upscaled) before they are composited, not after.
    captured = {}

    class Result:
        returncode = 0

    monkeypatch.setattr(overlayer.probe, "filtered_size", lambda p, f: (1080, 1920))
    monkeypatch.setattr(overlayer, "_video_fps", lambda p: "30")
    monkeypatch.setattr(overlayer, "_has_audio_stream", lambda p: True)
    monkeypatch.setattr(overlayer, "_get_video_codec", lambda: ("libx264", []))
    monkeypatch.setattr(overlayer.subprocess, "run", lambda cmd, *a, **k: captured.setdefault("cmd", cmd) and Result())

    overlayer._run_ffmpeg_overlay(
        Path("edit.mp4"), [{"asset": Path("x.mov"), "start": 1.0, "end": 3.0}], Path("out.mp4"),
        "scale=1080:1920:flags=lanczos",
    )
    graph = captured["cmd"][captured["cmd"].index("-filter_complex") + 1]
    assert graph.startswith("[0:v]scale=1080:1920:flags=lanczos,fps=30[base]")
    assert "scale=w=1080:h=1920" in graph  # overlay fitted to the filtered frame


class TestFitTemplateDurations:
    KEPT = [(0.0, 200.0)]

    def test_shortens_a_template_that_would_still_be_up(self):
        from tools.overlayer import _fit_template_durations
        a = {"template": "compare", "original_start": 49.5, "duration": 6}
        b = {"template": "chapter", "original_start": 54.06, "duration": 3}
        kept, dropped = _fit_template_durations([b, a], self.KEPT)
        assert kept == [a, b] and not dropped
        assert a["duration"] == pytest.approx(54.06 - 0.3 - 49.5)

    def test_drops_the_later_one_when_there_is_no_room(self):
        from tools.overlayer import _fit_template_durations
        a = {"template": "chapter", "original_start": 10.0, "duration": 3}
        b = {"template": "steps", "original_start": 10.8, "duration": 8}
        kept, dropped = _fit_template_durations([a, b], self.KEPT)
        assert kept == [a] and dropped == ["template:steps"]

    def test_leaves_spaced_overlays_alone(self):
        from tools.overlayer import _fit_template_durations
        a = {"template": "stat", "original_start": 5.0, "duration": 4}
        b = {"template": "quote", "original_start": 20.0, "duration": 5}
        kept, _ = _fit_template_durations([a, b], self.KEPT)
        assert a["duration"] == 4 and b["duration"] == 5


class TestCardsFollowTheTopic:
    def test_card_lasts_until_the_topic_ends(self):
        from tools.overlayer import _fit_template_durations, END_TAIL
        a = {"template": "steps", "original_start": 30.0, "original_end": 44.0, "duration": 5}
        kept, _ = _fit_template_durations([a], [(0.0, 200.0)])
        assert a["duration"] == pytest.approx(14.0 + END_TAIL)

    def test_topic_end_inside_a_cut_clamps_to_the_kept_part(self):
        from tools.overlayer import _fit_template_durations, END_TAIL
        a = {"template": "quote", "original_start": 2.0, "original_end": 15.0}
        _fit_template_durations([a], KEPT)  # 10-20s is cut
        assert a["duration"] == pytest.approx(8.0 + END_TAIL)

    def test_next_card_still_wins_over_a_long_topic(self):
        from tools.overlayer import _fit_template_durations
        a = {"template": "chapter", "original_start": 50.0, "original_end": 70.0}
        b = {"template": "quote", "original_start": 55.0, "original_end": 60.0}
        _fit_template_durations([a, b], [(0.0, 200.0)])
        assert a["duration"] == pytest.approx(4.7)

    def test_short_gap_to_the_next_card_is_closed(self):
        from tools.overlayer import _fit_template_durations
        a = {"template": "stat", "original_start": 10.0, "original_end": 13.0}  # 3.5s with tail
        b = {"template": "compare", "original_start": 14.2, "original_end": 20.0}
        _fit_template_durations([a, b], [(0.0, 200.0)])
        assert a["duration"] == pytest.approx(14.2 - 0.3 - 10.0)
