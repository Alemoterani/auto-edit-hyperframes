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


MAX_INSERT = 3        # Whisper drops short words ("Num", "Só"), not whole phrases
INSERT_WORD_SEC = 0.25
MIN_INSERT_GAP = 0.12  # seconds of room needed per dropped word


def _has_speech(t0: float, t1: float, energy: list[float], resolution: float, threshold: float) -> bool:
    lo, hi = int(t0 / resolution), int(t1 / resolution) + 1
    window = energy[max(0, lo):hi]
    return bool(window) and max(window) > threshold


def align(
    words: list[dict],
    script: str,
    energy: list[float] | None = None,
    resolution: float = 0.0,
    threshold: float | None = None,
) -> int:
    """Correct the transcription's words in place against the script. Returns how many changed.

    With an energy map (dB per `resolution` seconds) and its silence `threshold`,
    script words Whisper dropped ("Num bairro" heard as "bairro") are inserted
    right before the next word — only if there is room and the audio there is
    speech, so script lines that weren't said never become captions.
    """
    target = script_words(script)
    if not words or not target:
        return 0
    a = [_norm(w.get("word", "")) for w in words]
    b = [_norm(w) for w in target]
    changed = 0
    inserts: list[tuple[int, list[str]]] = []
    for op, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "insert" and energy and resolution and threshold is not None and 0 < i1 < len(words) and j2 - j1 <= MAX_INSERT:
            inserts.append((i1, target[j1:j2]))
            continue
        if op not in ("equal", "replace") or (i2 - i1) != (j2 - j1):
            continue
        for i, j in zip(range(i1, i2), range(j1, j2)):
            if op == "replace" and SequenceMatcher(None, a[i], b[j]).ratio() < MIN_SIMILARITY:
                continue
            new = target[j]
            if words[i].get("word", "").strip() != new:
                words[i]["word"] = new
                changed += 1

    # Back to front, so earlier indexes stay valid while inserting.
    for i, missing in reversed(inserts):
        prev_end, next_start = float(words[i - 1]["end"]), float(words[i]["start"])
        if next_start - prev_end < MIN_INSERT_GAP * len(missing):
            continue
        start = max(prev_end, next_start - INSERT_WORD_SEC * len(missing))
        if not _has_speech(start, next_start, energy, resolution, threshold):
            continue
        step = (next_start - start) / len(missing)
        new_words = [
            {"word": w, "start": round(start + k * step, 3), "end": round(start + (k + 1) * step, 3), "inserted": True}
            for k, w in enumerate(missing)
        ]
        words[i:i] = new_words
        changed += len(new_words)
    return changed


def apply_to_transcription(t: dict, script: str) -> int:
    """align() on a transcription dict ({words, segments, energy_db_fine, ...}), keeping
    each segment's words and text in step. Returns how many words changed."""
    from auto_edit import snap

    energy = t.get("energy_db_fine") or t.get("energy_db") or []
    resolution = float(t.get("fine_resolution_seconds") or t.get("resolution_seconds") or 0.0)
    threshold = snap.silence_threshold_db(energy) if energy else None
    words = t.get("words", [])
    changed = align(words, script, energy, resolution, threshold)

    segments = t.get("segments", [])
    if segments:
        # Reassign words to segments by start time (inserted words land in the right one).
        buckets: list[list[dict]] = [[] for _ in segments]
        k = 0
        for w in words:
            while k + 1 < len(segments) and float(w["start"]) >= float(segments[k + 1]["start"]):
                k += 1
            buckets[k].append(w)
        for seg, seg_words in zip(segments, buckets):
            if seg_words:
                seg["words"] = seg_words
                seg["text"] = " ".join(w["word"] for w in seg_words)
    return changed


if __name__ == "__main__":
    demo = [{"word": w, "start": i, "end": i + 0.5} for i, w in enumerate(
        "o pao era bom e o preco justo culpa dos especulador de trigo".split())]
    n = align(demo, 'ATO 1: A promessa (0:15)\n"O pão era bom e o preço, justo." (pausa) “Culpa dos especuladores de trigo.”')
    assert [w["word"] for w in demo] == ["O", "pão", "era", "bom", "e", "o", "preço,", "justo.", "Culpa", "dos", "especuladores", "de", "trigo."], demo
    assert n == 7 and demo[2]["start"] == 2

    # Dropped word: "os começaram" with a 0.4s gap of speech -> "os padeiros começaram".
    w = [{"word": "os", "start": 1.0, "end": 1.2}, {"word": "começaram", "start": 1.6, "end": 2.0}]
    loud = [-20.0] * 30
    assert align(w, "os padeiros começaram", loud, 0.1, -32.0) == 1
    assert [x["word"] for x in w] == ["os", "padeiros", "começaram"] and w[1]["start"] >= 1.2
    # Same gap but silent: nothing inserted.
    w = [{"word": "os", "start": 1.0, "end": 1.2}, {"word": "começaram", "start": 1.6, "end": 2.0}]
    assert align(w, "os padeiros começaram", [-60.0] * 30, 0.1, -32.0) == 0
    print("ok")
