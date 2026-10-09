"""Correct transcribed words against the video's script (roteiro), locally.

Aligns the Whisper words to the script's words (difflib) and, where both say
the same thing, writes the script's spelling over the transcription, keeping
Whisper's timestamps. Only one-for-one swaps are made, so parts the speaker
improvised or cut stay exactly as spoken:

- "equal" spans (same words up to accents/case/punctuation) take the script's
  accents and punctuation ("pao" -> "pão,");
- "replace" spans with the same word count take the script word when it looks
  like a mishearing of it ("especulador" -> "especuladores").
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

# Stage directions like "(câmera direta, tom calmo)" and headings like
# "ATO 1: A promessa (0:15 – 0:55)" are not spoken.
_PARENS = re.compile(r"\([^)]*\)")
_HEADING = re.compile(r"^\s*(roteiro|gancho|ato\s+\d+|fechamento|cena|cta)\b.*$", re.IGNORECASE | re.MULTILINE)
_TOKEN = re.compile(r"\S+")
_QUOTES = re.compile(r"[\"“”]|(?<!\w)['‘’]|['‘’](?!\w)")
MIN_SIMILARITY = 0.6


def _norm(word: str) -> str:
    stripped = "".join(c for c in unicodedata.normalize("NFD", word.lower()) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^\w]", "", stripped)


def script_words(script: str) -> list[str]:
    """Spoken words of the script, with their punctuation, in order."""
    text = _HEADING.sub(" ", _PARENS.sub(" ", script))
    # Drop quote marks ('de graça'? -> de graça?) but keep apostrophes inside words (d'água).
    words = [_QUOTES.sub("", w) for w in _TOKEN.findall(text)]
    return [w for w in words if _norm(w)]


def align(words: list[dict], script: str) -> int:
    """Rewrite `word` in-place on the transcription's word dicts. Returns how many changed."""
    target = script_words(script)
    if not words or not target:
        return 0
    a = [_norm(w.get("word", "")) for w in words]
    b = [_norm(w) for w in target]
    changed = 0
    for op, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op not in ("equal", "replace") or (i2 - i1) != (j2 - j1):
            continue
        for i, j in zip(range(i1, i2), range(j1, j2)):
            if op == "replace" and SequenceMatcher(None, a[i], b[j]).ratio() < MIN_SIMILARITY:
                continue
            new = target[j]
            if words[i].get("word", "").strip() != new:
                words[i]["word"] = new
                changed += 1
    return changed


if __name__ == "__main__":
    demo = [{"word": w, "start": i, "end": i + 0.5} for i, w in enumerate(
        "o pao era bom e o preco justo culpa dos especulador de trigo".split())]
    n = align(demo, 'ATO 1: A promessa (0:15)\n"O pão era bom e o preço, justo." (pausa) “Culpa dos especuladores de trigo.”')
    assert [w["word"] for w in demo] == ["O", "pão", "era", "bom", "e", "o", "preço,", "justo.", "Culpa", "dos", "especuladores", "de", "trigo."], demo
    assert n == 7 and demo[2]["start"] == 2
    print("ok")
