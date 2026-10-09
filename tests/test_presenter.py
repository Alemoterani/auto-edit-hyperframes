"""Testes de auto_edit/presenter.py + auto_edit/backdrop.py (recorte local; a sessão do modelo é simulada)."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))

from auto_edit import backdrop, pipeline as pl, presenter


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_EDIT_HOME", str(tmp_path))
    return tmp_path


class FakeSession:
    """Faz o papel da sessão onnx do RVM: alpha = 1 na metade esquerda, 0 na direita."""

    def run(self, _outputs, feed):
        _, _, h, w = feed["src"].shape
        pha = np.zeros((1, 1, h, w), np.float32)
        pha[..., : w // 2] = 1.0
        states = [np.zeros((1, 1, 1, 1), np.float32)] * 4
        return [feed["src"], pha, *states]


def test_config_roundtrip_missing_and_corrupt(home):
    assert presenter.load_config() == {}
    presenter.save_config({"default_backdrop": "neutral"})
    assert presenter.load_config()["default_backdrop"] == "neutral"
    (home / "presenter.json").write_text("{nope", encoding="utf-8")
    assert presenter.load_config() == {}


def test_pick_backdrop_topic_case_insensitive_and_default():
    cfg = {"default_backdrop": "neutral", "topics": {"Finanças": {"backdrop": "finance"}, "x": {}}}
    assert presenter.pick_backdrop(cfg, "dicas de FINANÇAS") == "finance"
    assert presenter.pick_backdrop(cfg, "culinária") == "neutral"
    assert presenter.pick_backdrop({}, "qualquer") is None


def test_backdrop_file_theme_is_rendered_and_cached_and_path_is_checked(tmp_path):
    out = presenter.backdrop_file("finance")
    assert out.is_file() and Image.open(out).size == presenter.BACKDROP_SIZE
    first = out.stat().st_mtime_ns
    assert presenter.backdrop_file("finance").stat().st_mtime_ns == first  # veio do cache
    img = tmp_path / "me.png"
    Image.new("RGB", (8, 8)).save(img)
    assert presenter.backdrop_file(str(img)) == img
    assert presenter.backdrop_file(str(tmp_path / "missing.png")) is None


def test_thumbnail_backdrop_needs_flag():
    presenter.save_config({"default_backdrop": "neutral"})
    assert presenter.thumbnail_backdrop("x") is None
    presenter.save_config({"default_backdrop": "neutral", "thumbnail": True})
    assert presenter.thumbnail_backdrop("x").name == "neutral.png"


def test_cover_crops_to_exact_size_without_distortion():
    img = Image.new("RGB", (200, 100), (255, 0, 0))
    assert backdrop.cover(img, (50, 50)).size == (50, 50)


def test_matte_size_is_even_and_capped():
    assert backdrop.matte_size(1080, 1920) == (768, 1364)
    mw, mh = backdrop.matte_size(320, 240)
    assert (mw, mh) == (320, 240)


def test_matter_alpha_matches_frame_size_and_range():
    frame = np.full((90, 160, 3), 200, np.uint8)
    a = backdrop.Matter(FakeSession()).alpha(frame)
    assert a.shape == (90, 160) and a.dtype == np.float32
    assert a[:, 0].min() > 0.9 and a[:, -1].max() < 0.1


def test_composite_blends_by_alpha():
    fg = np.full((2, 2, 3), 200, np.float32)
    bg = np.full((2, 2, 3), 0, np.float32)
    out = backdrop.composite(fg, np.array([[1.0, 0.0], [0.5, 0.0]], np.float32), bg)
    assert out[0, 0, 0] == 200 and out[0, 1, 0] == 0 and out[1, 0, 0] == 100


def test_swap_image_puts_person_over_backdrop(tmp_path):
    src, bgp, out = tmp_path / "f.png", tmp_path / "b.png", tmp_path / "o.png"
    Image.new("RGB", (160, 90), (200, 0, 0)).save(src)
    Image.new("RGB", (160, 90), (0, 0, 200)).save(bgp)
    backdrop.swap_image(src, bgp, out, matter=backdrop.Matter(FakeSession()))
    px = Image.open(out)
    assert px.getpixel((5, 45))[0] > 150      # metade esquerda = pessoa (vermelho)
    assert px.getpixel((155, 45))[2] > 150    # metade direita = fundo (azul)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_swap_video_keeps_every_frame_and_the_audio(tmp_path):
    """Regressão: com `-shortest`, um corte cujo áudio termina um pouco antes do vídeo (normal
    na saída do executor) perdia os últimos quadros de vídeo."""
    src, bgp, out = tmp_path / "in.mp4", tmp_path / "bg.png", tmp_path / "out.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=30:duration=1",
                    "-f", "lavfi", "-i", "sine=duration=0.8", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(src)], check=True)
    Image.new("RGB", (64, 64), (0, 0, 200)).save(bgp)
    backdrop.swap_video(src, bgp, out, matter=backdrop.Matter(FakeSession()))

    def count(path, stream):
        r = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", stream,
                            "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(path)],
                           capture_output=True, text=True)
        return r.stdout.strip()

    assert count(out, "v:0") == count(src, "v:0") == "30"
    assert count(out, "a:0") == count(src, "a:0")
    assert not (tmp_path / "out.bg.png").exists()  # o fundo temporário foi apagado


def _workspace(tmp_path, backdrop_flag=True):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "edited_video.mp4").write_bytes(b"cut")
    (ws / "pipeline.json").write_text(
        json.dumps({"backdrop": backdrop_flag, "context": "finanças"}), encoding="utf-8")
    return ws


def test_hook_off_without_flag(tmp_path):
    ws = _workspace(tmp_path, backdrop_flag=False)
    assert backdrop.run_for_workspace(ws) is False
    assert (ws / "edited_video.mp4").read_bytes() == b"cut"


def test_hook_skips_when_no_backdrop_configured(tmp_path):
    ws = _workspace(tmp_path)
    assert backdrop.run_for_workspace(ws) is False
    assert (ws / "edited_video.mp4").read_bytes() == b"cut"


def test_hook_swaps_keeps_original_and_is_idempotent(tmp_path, monkeypatch):
    presenter.save_config({"topics": {"finanças": {"backdrop": "finance"}}})
    ws = _workspace(tmp_path)
    calls = []

    def fake_swap(src, bd, dst, **kw):
        calls.append(src.name)
        dst.write_bytes(b"swapped")
        return dst

    monkeypatch.setattr(backdrop, "swap_video", fake_swap)
    assert backdrop.run_for_workspace(ws) is True
    assert (ws / "edited_video.mp4").read_bytes() == b"swapped"
    assert (ws / "edited_video_original.mp4").read_bytes() == b"cut"
    assert backdrop.run_for_workspace(ws) is False  # mesmo corte, já trocado
    assert calls == ["edited_video.mp4"]
    assert not (ws / "edited_video.backdrop.mp4").exists()
    (ws / "edited_video.mp4").write_bytes(b"new cut")  # o executor rodou de novo
    assert backdrop.run_for_workspace(ws) is True
    assert (ws / "edited_video_original.mp4").read_bytes() == b"new cut"


def test_hook_restores_cut_when_swap_fails(tmp_path, monkeypatch):
    presenter.save_config({"default_backdrop": "neutral"})
    ws = _workspace(tmp_path)

    def boom(src, bd, dst, **kw):
        dst.write_bytes(b"half a video")  # caiu no meio do render
        raise RuntimeError("ffmpeg died")

    monkeypatch.setattr(backdrop, "swap_video", boom)
    assert backdrop.run_for_workspace(ws) is False
    assert (ws / "edited_video.mp4").read_bytes() == b"cut"
    assert not (ws / "edited_video.backdrop.mp4").exists()  # o render pela metade foi apagado
    assert not (ws / "edited_video_original.mp4").exists()


def test_set_backdrop_flag_persists(tmp_path):
    ws = _workspace(tmp_path, backdrop_flag=False)
    pl.set_backdrop(ws)
    assert pl.load(ws)["backdrop"] is True
