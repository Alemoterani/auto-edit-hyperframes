"""Testes de auto_edit/portrait.py (o Gemini e o recorte são simulados)."""
import json
import sys
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))

from auto_edit import portrait


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_EDIT_HOME", str(tmp_path))
    return tmp_path


def test_prompt_has_topic_outfit_scene_and_identity_rules():
    p = portrait.build_prompt("finanças pessoais")
    assert portrait.TOPICS["finanças"]["outfit"] in p
    assert portrait.TOPICS["finanças"]["scene"] in p
    assert portrait.IDENTITY_RULES in p and portrait.RELIGHT in p and portrait.RETOUCH in p


def test_unknown_topic_is_neutral_and_config_overrides(home):
    assert portrait.topic_style("culinária") == {**portrait.TOPICS["neutro"]}
    (home / "presenter.json").write_text(json.dumps(
        {"topics": {"Finanças": {"backdrop": "finance", "outfit": "colete de lã", "accent": [1, 2, 3]}}}),
        encoding="utf-8")
    s = portrait.topic_style("finanças")
    assert s["outfit"] == "colete de lã" and s["accent"] == (1, 2, 3)
    assert s["scene"] == portrait.TOPICS["finanças"]["scene"]


class FakeClient:
    """Faz o papel do genai.Client: devolve uma imagem por chamada (a 2ª chamada vem sem imagem)."""

    def __init__(self):
        self.calls = []
        self.models = self

    def generate_content(self, model, contents, config=None):
        self.calls.append((model, contents))
        self.config = config
        if len(self.calls) == 2:
            return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[]))])
        buf = BytesIO()
        Image.new("RGB", (40, 60), (10, 20, 30)).save(buf, "PNG")
        part = SimpleNamespace(inline_data=SimpleNamespace(data=buf.getvalue()))
        return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))])


def test_dress_saves_each_returned_image_and_skips_empty(tmp_path):
    photo = tmp_path / "eu.jpg"
    Image.new("RGB", (40, 60)).save(photo)
    client = FakeClient()
    saved = portrait.dress(photo, "tecnologia", tmp_path / "out", n=3, client=client)
    assert [p.name for p in saved] == ["eu_tecnologia_1.png", "eu_tecnologia_3.png"]
    assert len(client.calls) == 3
    model, (img, prompt) = client.calls[0]
    assert model == portrait.DEFAULT_MODEL
    assert img.size == (40, 60) and prompt == portrait.build_prompt("tecnologia")


def test_dress_sends_reference_photos_expression_and_scene(tmp_path):
    photo, side = tmp_path / "frente.jpg", tmp_path / "perfil.jpg"
    Image.new("RGB", (40, 60)).save(photo)
    Image.new("RGB", (30, 50)).save(side)
    client = FakeClient()
    portrait.dress(photo, "política", tmp_path, n=1, client=client, refs=[side],
                   expression="sério e cético", scene="um porto de contêineres")
    _, (base, ref, prompt) = client.calls[0]
    assert base.size == (40, 60) and ref.size == (30, 50)
    assert portrait.REFS_NOTE in prompt and "sério e cético" in prompt and "um porto de contêineres" in prompt
    assert portrait.TOPICS["política"]["scene"] not in prompt


@pytest.mark.parametrize("size", list(portrait.SIZES.values()))
def test_compose_outputs_layout_size_with_highlight_bar(size):
    img = Image.new("RGB", (400, 600), (120, 90, 70))
    alpha = np.zeros((600, 400), np.float32)
    alpha[150:, 100:300] = 1.0  # "você" no meio da foto
    out = portrait.compose(img, alpha, size, "juros", "o preço do pão", "ninguém conta",
                           accent=(255, 190, 60), signature="@eu")
    assert out.size == size and out.mode == "RGB"
    px = np.asarray(out).reshape(-1, 3)
    assert (np.abs(px - portrait.HIGHLIGHT).sum(1) < 10).any()  # a faixa amarela da marca está lá


def test_dress_aspect_builds_theme_scene_and_asks_that_ratio(tmp_path):
    photo = tmp_path / "eu.jpg"
    Image.new("RGB", (40, 60)).save(photo)
    client = FakeClient()
    saved = portrait.dress(photo, "política", tmp_path, n=1, client=client, aspect="16:9",
                           elements="guindastes e contêineres", word="SOBERANIA")
    prompt = client.calls[0][1][-1]
    assert portrait.LAYOUTS["16:9"] in prompt and portrait.INTEGRATE in prompt
    assert "guindastes e contêineres" in prompt and '"SOBERANIA"' in prompt
    assert client.config["image_config"] == {"aspect_ratio": "16:9"}
    assert saved[0].name == "eu_política_16x9_1.png"


def test_compose_ready_scene_only_adds_typography():
    img = Image.new("RGB", (1280, 720), (90, 60, 40))
    out = portrait.compose(img, None, (1280, 720), "", "o brasil já tem dono", "ninguém te conta")
    assert out.size == (1280, 720)
    assert (np.abs(np.asarray(out).reshape(-1, 3) - portrait.HIGHLIGHT).sum(1) < 10).any()
