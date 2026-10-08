"""Tests for auto_edit/hyperframes.py (no Node needed: the render call is stubbed)."""
from pathlib import Path

import pytest

from auto_edit import hyperframes


def test_patch_root_rewrites_size_and_duration_once():
    html = (
        '<html><head></head><body><div id="root" data-duration="4" data-width="1920" data-height="1080">'
        '<section data-duration="4"></section></div></body></html>'
    )
    out = hyperframes._patch_root(html, 1080, 1920, 7.5)
    assert 'data-duration="7.500" data-width="1080" data-height="1920"' in out
    assert '<section data-duration="4">' in out  # only the root is touched
    assert "#root{width:1080px;height:1920px}" in out


def test_every_shipped_template_resolves():
    for name in ("lower_third", "cta", "highlight", "steps", "stat", "compare", "code", "chart", "chapter", "quote", "captions"):
        assert (hyperframes.template_dir(name) / "index.html").is_file()


def test_unknown_template_raises():
    with pytest.raises(FileNotFoundError):
        hyperframes.template_dir("nope")


def test_render_writes_data_and_reuses_cache(monkeypatch, tmp_path):
    calls = []

    class Result:
        returncode = 0
        stdout = stderr = ""

    def fake_run(cmd, **kwargs):
        project = Path(cmd[cmd.index("render") + 1])
        calls.append((project / "data.js").read_text(encoding="utf-8"))
        Path(cmd[cmd.index("-o") + 1]).write_bytes(b"mov")
        return Result()

    monkeypatch.setattr(hyperframes, "npx", lambda: "npx")
    monkeypatch.setattr(hyperframes.subprocess, "run", fake_run)

    args = ("cta", {"text": "Se inscreve"}, tmp_path, 1920, 1080, 4.0, "30")
    first = hyperframes.render(*args)
    second = hyperframes.render(*args)

    assert first == second and first.suffix == ".mov"
    assert len(calls) == 1  # second call is a cache hit
    assert '"text": "Se inscreve"' in calls[0]


def test_render_without_node_fails_clearly(monkeypatch, tmp_path):
    monkeypatch.setattr(hyperframes, "npx", lambda: None)
    with pytest.raises(RuntimeError, match="Node.js"):
        hyperframes.render("cta", {}, tmp_path, 1920, 1080, 4.0)


def test_render_pins_the_vendored_version():
    # vendor/hyperframes ships with the repo; npx must run that exact version.
    assert hyperframes.package_spec().startswith("hyperframes@0.")


def test_missing_vendor_falls_back_to_latest(monkeypatch, tmp_path):
    monkeypatch.setattr(hyperframes, "VENDOR_CLI_PACKAGE", tmp_path / "nope.json")
    assert hyperframes.package_spec() == "hyperframes"


def test_render_defaults_to_one_worker(monkeypatch, tmp_path):
    seen = {}

    class Result:
        returncode = 0
        stdout = stderr = ""

    def fake_run(cmd, **kwargs):
        seen["workers"] = cmd[cmd.index("--workers") + 1]
        Path(cmd[cmd.index("-o") + 1]).write_bytes(b"mov")
        return Result()

    monkeypatch.setattr(hyperframes, "npx", lambda: "npx")
    monkeypatch.setattr(hyperframes.subprocess, "run", fake_run)
    monkeypatch.delenv("AUTO_EDIT_HF_WORKERS", raising=False)
    hyperframes.render("cta", {}, tmp_path, 640, 360, 1.0)
    assert seen["workers"] == "1"
