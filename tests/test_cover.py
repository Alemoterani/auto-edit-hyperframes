"""Testes da capa em motion graphics: Pexels, render com fotos, folha de opções e a abertura sem empilhar."""
import io
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))

from auto_edit import cover, hyperframes, stock  # noqa: E402
from tools import overlayer, thumbnailer  # noqa: E402


def test_search_needs_key(monkeypatch):
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="PEXELS_API_KEY"):
        stock.search("port")


def test_search_parses_photos_and_sends_key(monkeypatch):
    monkeypatch.setenv("PEXELS_API_KEY", "k123")
    seen = {}
    body = {"photos": [{"id": 1, "alt": "cranes", "photographer": "Ana", "src": {"large2x": "https://x/1.jpg"}},
                       {"id": 2, "src": {"large2x": "https://x/2.jpg"}}]}

    def fake_open(req, timeout=30):
        seen["url"], seen["auth"] = req.full_url, req.get_header("Authorization")
        return io.BytesIO(json.dumps(body).encode())

    monkeypatch.setattr(stock, "_open", fake_open)
    photos = stock.search("container port", "portrait", 2)
    assert [p["url"] for p in photos] == ["https://x/1.jpg", "https://x/2.jpg"]
    assert photos[0]["photographer"] == "Ana" and seen["auth"] == "k123"
    assert "orientation=portrait" in seen["url"] and "per_page=2" in seen["url"]


def test_from_metadata_maps_thumbnail_fields():
    data = cover.from_metadata({"thumbnail": {"main_text": "O BRASIL JÁ TEM DONO", "sub_text": "NINGUÉM TE CONTA",
                                              "word": "SOBERANIA", "image_queries": ["port"], "template": "maker"}})
    assert data["word"] == "SOBERANIA" and data["queries"] == ["port"]
    assert data["accent"] == "#ff9f2e"  # cor do template maker em assets/thumbnails/templates.json


def test_render_copies_photos_and_they_enter_the_cache_key(tmp_path, monkeypatch):
    photo = tmp_path / "a.jpg"
    photo.write_bytes(b"one")
    copied = []

    def fake_run(cmd, **kw):
        project = Path(cmd[cmd.index("render") + 1])
        copied.append((project / "img0.jpg").read_bytes())
        Path(cmd[cmd.index("-o") + 1]).write_bytes(b"mov")
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(hyperframes, "npx", lambda: "npx")
    monkeypatch.setattr(hyperframes.subprocess, "run", fake_run)
    first = hyperframes.render("cover", {}, tmp_path / "out", 1080, 1920, 2.5, files={"img0.jpg": photo})
    photo.write_bytes(b"two")
    second = hyperframes.render("cover", {}, tmp_path / "out", 1080, 1920, 2.5, files={"img0.jpg": photo})
    assert copied == [b"one", b"two"] and first != second


def test_contact_sheet_has_a_tile_per_option(tmp_path):
    opts = []
    for i in range(5):
        p = tmp_path / f"o{i}.jpg"
        Image.new("RGB", (400, 300), (i * 40, 80, 120)).save(p)
        opts.append(p)
    sheet = cover.contact_sheet(opts, tmp_path / "folha.png", thumb=100)
    with Image.open(sheet) as im:
        assert im.size == (400, 200)  # 4 por linha, 2 linhas


def test_hook_restarts_from_the_original_instead_of_stacking(tmp_path, monkeypatch):
    video, mov = tmp_path / "captioned_video.mp4", tmp_path / "cover.mov"
    video.write_bytes(b"original")
    mov.write_bytes(b"anim")

    def fake_overlay(src, placed, out, video_filter=None):
        out.write_bytes(src.read_bytes() + b"+hook")

    monkeypatch.setattr(overlayer, "_run_ffmpeg_overlay", fake_overlay)
    thumbnailer._apply_hook(tmp_path, video, mov)
    assert video.read_bytes() == b"original+hook"
    (tmp_path / thumbnailer.HOOK_STAMP).write_text(json.dumps({"mtime": video.stat().st_mtime_ns}))
    thumbnailer._apply_hook(tmp_path, video, mov)  # nova rodada: parte do original guardado
    assert video.read_bytes() == b"original+hook"
    assert (tmp_path / thumbnailer.HOOK_SOURCE).read_bytes() == b"original"


def test_stage_falls_back_to_classic_cover_when_motion_fails(tmp_path, monkeypatch):
    (tmp_path / "pipeline.json").write_text(json.dumps({"type": "short"}))
    (tmp_path / "metadata.json").write_text(json.dumps({"thumbnail": {"main_text": "X", "word": "Y"}}))
    monkeypatch.setattr(cover, "render", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("sem npx")))
    classic = tmp_path / "thumbnail.png"
    monkeypatch.setattr(thumbnailer, "_thumbnail_short", lambda *a: classic)
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    embedded = []
    monkeypatch.setattr(thumbnailer, "_embed_cover_frame", lambda ws, thumb: embedded.append(thumb))
    thumbnailer.thumbnail(tmp_path)
    assert embedded == [classic]
