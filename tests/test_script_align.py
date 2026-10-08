"""Tests for auto_edit/script_align.py — correcting the transcription with the roteiro."""
from auto_edit import script_align
from auto_edit import pipeline as pl
from auto_edit.looks import LOOKS


def _words(text):
    return [{"word": w, "start": float(i), "end": i + 0.5} for i, w in enumerate(text.split())]


SCRIPT = """Roteiro: "A Padaria do Bairro" (3 min)

GANCHO (0:00 – 0:15)
(câmera direta, tom calmo)
"Vou te contar uma história sobre uma padaria."

ATO 1: A promessa (0:15 – 0:55)
"O pão era bom e o preço, justo."
"""


def test_headings_and_stage_directions_are_not_spoken():
    words = script_align.script_words(SCRIPT)
    assert words[:4] == ["Vou", "te", "contar", "uma"]
    assert "GANCHO" not in words and "câmera" not in words and "promessa" not in words


def test_fixes_accents_and_mishearings_keeping_timestamps():
    w = _words("vou te contar uma historia sobre uma padaria o pao era bom e o preco justo")
    script_align.align(w, SCRIPT)
    assert [x["word"] for x in w][4:] == ["história", "sobre", "uma", "padaria.", "O", "pão", "era", "bom", "e", "o", "preço,", "justo."]
    assert w[9]["start"] == 9.0


def test_improvised_words_stay_as_spoken():
    # The speaker said something the script doesn't have: nothing to align it to.
    w = _words("então pessoal hoje é sobre uma padaria")
    script_align.align(w, SCRIPT)
    assert [x["word"] for x in w][:3] == ["então", "pessoal", "hoje"]


def test_unrelated_word_is_not_replaced():
    w = _words("o pão era ótimo e o preço justo")
    script_align.align(w, SCRIPT)
    assert w[3]["word"] == "ótimo"  # "bom" vs "ótimo" is a rewording, not a mishearing


def test_options_are_stored_on_the_pipeline(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    video = tmp_path / "v.mp4"
    video.write_text("")
    pl.init(ws, video, "short", "ctx")
    pl.set_option(ws, "script", SCRIPT)
    pl.set_option(ws, "video_filter", LOOKS["low-light"])
    p = pl.load(ws)
    assert p["script"] == SCRIPT and "scale=1080:1920" in p["video_filter"]
