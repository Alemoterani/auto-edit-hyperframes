"""
Portrait: sua foto vestida e iluminada conforme o assunto (Gemini) + a capa na identidade "Autoridade Editorial".

Dois passos, cada um com o seu comando (``auto-edit presenter dress`` / ``thumb``):

1. ``dress``: manda a foto ao modelo de edição de imagem do Gemini (``GEMINI_API_KEY``) pedindo SÓ roupa, cenário e
   luz de estúdio — rosto, pele e cabelo intactos. Gera algumas variantes; você escolhe a mais fiel.
2. ``compose``: recorta você (RVM local, ``backdrop.Matter``), desenha a palavra gigante atrás da cabeça, rim light na
   cor do assunto, vinheta, faixa amarela + título. Sai em 16:9 (1280x720) e 9:16 (1080x1920).

Roupa/cenário de cada assunto: ``TOPICS``; ``~/.auto-edit/presenter.json`` pode sobrescrever por assunto
(``topics.<assunto>.outfit`` / ``scene`` / ``accent``) e definir ``signature`` (seu nome/@ no canto da capa).
"""
from __future__ import annotations

import os
import sys
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from auto_edit import backdrop, presenter

DEFAULT_MODEL = "gemini-2.5-flash-image"  # AUTO_EDIT_IMAGE_MODEL troca quando o Google aposentar este
HIGHLIGHT = (255, 212, 0)                 # #FFD400: a faixa da marca, igual em todo assunto
WORD_COLOR = (238, 236, 230)
SIZES = {"16x9": (1280, 720), "9x16": (1080, 1920)}

_POLITICA = {
    "outfit": "a tailored charcoal-gray suit with a crisp white shirt, no tie",
    "scene": "a modern TV news studio with screens and soft blue lights, strongly blurred",
    "accent": (90, 160, 255),
}
TOPICS = {
    "finanças": {
        "outfit": "a tailored navy-blue suit with a crisp white shirt, no tie",
        "scene": "an executive office with market charts on screens and a city view, strongly blurred",
        "accent": (255, 190, 60),
    },
    "política": _POLITICA,
    "notícias": _POLITICA,
    "tecnologia": {
        "outfit": "a premium plain black t-shirt under a dark blazer",
        "scene": "a tech workspace with monitors and cyan LED lights, strongly blurred",
        "accent": (40, 220, 255),
    },
    "educação": {
        "outfit": "a light button-down shirt with a navy blazer",
        "scene": "a warm library with tall bookshelves, strongly blurred",
        "accent": (255, 170, 70),
    },
    "saúde": {
        "outfit": "a white doctor's lab coat over a light-blue shirt",
        "scene": "a modern bright medical clinic, strongly blurred",
        "accent": (60, 220, 190),
    },
    "neutro": {
        "outfit": "a dark tailored button-down shirt",
        "scene": "a seamless gray studio backdrop with a soft gradient",
        "accent": (255, 255, 255),
    },
}

IDENTITY_RULES = (
    "Keep the person's face EXACTLY as in the photo: same face shape, eyes, nose, mouth, skin tone, hair, "
    "facial hair, age and expression. Do not beautify, slim, smooth, reshape or change identity in any way. "
    "Keep the same head pose and framing."
)


def topic_style(topic: str) -> dict:
    """Roupa, cenário e cor do assunto: a config do presenter sobrescreve o padrão; assunto desconhecido = neutro."""
    t = (topic or "").lower()
    base = next((v for k, v in TOPICS.items() if k in t), TOPICS["neutro"])
    user = next((v for k, v in (presenter.load_config().get("topics") or {}).items() if k.lower() in t), {})
    style = {**base, **{k: user[k] for k in ("outfit", "scene", "accent") if user.get(k)}}
    style["accent"] = tuple(style["accent"])
    return style


def build_prompt(topic: str) -> str:
    s = topic_style(topic)
    return (
        "Edit this photo into a professional portrait. "
        f"{IDENTITY_RULES} "
        f"Change ONLY: the clothing to {s['outfit']}, conveying authority; the background to {s['scene']}, "
        "shallow depth of field; the lighting to soft studio key light with a subtle rim light. "
        "Correct exposure and white balance and remove only minor skin blemishes. "
        "Photorealistic, natural, no filters, no text, no logos."
    )


def _client():
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("Defina GEMINI_API_KEY para trocar roupa/cenário")
    try:
        from google import genai  # import tardio: dependência opcional (extra backdrop)
    except ImportError:
        raise RuntimeError('Falta o google-genai: pip install -e ".[backdrop]"') from None
    return genai.Client(api_key=key)


def dress(photo: Path, topic: str, out_dir: Path, n: int = 3, client=None) -> list[Path]:
    """Gera ``n`` variantes da foto vestida/iluminada para o assunto. Devolve os PNGs salvos."""
    with Image.open(photo) as f:
        img = ImageOps.exif_transpose(f).convert("RGB")  # foto de celular vem deitada sem isso
    client = client or _client()
    contents = [img, build_prompt(topic)]  # o google-genai aceita a imagem PIL direto
    model = os.environ.get("AUTO_EDIT_IMAGE_MODEL", DEFAULT_MODEL)
    slug = (topic or "neutro").split()[0].lower()
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for i in range(1, n + 1):
        resp = client.models.generate_content(model=model, contents=contents)
        parts = resp.candidates[0].content.parts if resp.candidates else []
        data = next((p.inline_data.data for p in parts if getattr(p, "inline_data", None)), None)
        if data is None:
            print(f"[portrait] variante {i}: o modelo não devolveu imagem")
            continue
        out = out_dir / f"{photo.stem}_{slug}_{i}.png"
        Image.open(BytesIO(data)).convert("RGB").save(out, "PNG")
        saved.append(out)
    return saved


# ── Capa ────────────────────────────────────────────────────────────────────


def matte(img: Image.Image) -> np.ndarray:
    """Alpha (HxW float 0..1) de você na foto, com o RVM local."""
    frame = np.asarray(img.convert("RGB"))
    m = backdrop.Matter()
    for _ in range(backdrop.WARMUP):
        alpha = m.alpha(frame)
    return alpha


def _thumb():
    """tools/thumbnailer.py (fontes e quebra de linha); ele vive fora do pacote, na raiz do repo."""
    root = str(Path(__file__).resolve().parent.parent)
    if root not in sys.path:
        sys.path.insert(0, root)
    from tools import thumbnailer
    return thumbnailer


def _blur(arr: np.ndarray, r: float) -> np.ndarray:
    """Desfoque gaussiano de um array float 0..1 (HxW ou HxWx3)."""
    img = Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8))
    return np.asarray(img.filter(ImageFilter.GaussianBlur(r)), dtype=np.float32) / 255.0


def _clean_plate(img: np.ndarray, alpha: np.ndarray, r: float) -> np.ndarray:
    """Cenário sem você: o buraco do recorte é preenchido com a média desfocada do que está em volta."""
    inv = 1.0 - alpha
    num = _blur(img * inv[..., None], r)
    den = _blur(inv, r)[..., None]
    return np.where(den > 0.02, num / np.maximum(den, 1e-3), _blur(img, r))


def compose(
    portrait: Image.Image, alpha: np.ndarray, size: tuple[int, int], word: str, title: str,
    highlight: str = "", accent: tuple[int, int, int] = (255, 255, 255), signature: str = "",
) -> Image.Image:
    """Capa no layout da identidade: 16:9 você à direita e texto à esquerda; 9:16 você no centro e texto embaixo."""
    th = _thumb()
    w, h = size
    wide = w > h
    src = np.asarray(portrait.convert("RGB"), dtype=np.float32) / 255.0

    # Fundo: o cenário da foto sem você, bem desfocado e escurecido (você é o que tem foco)
    plate = _clean_plate(src, alpha, max(src.shape[:2]) / 25)
    bg = backdrop.cover(Image.fromarray((plate * 255).astype(np.uint8)), size).filter(ImageFilter.GaussianBlur(6))
    canvas = np.asarray(bg, dtype=np.float32) / 255.0 * 0.7

    # Você: escala pela altura, base colada embaixo, centro do recorte na posição do layout
    scale = h * (1.02 if wide else 0.80) / portrait.height
    pw, ph = round(portrait.width * scale), round(portrait.height * scale)
    person = np.asarray(portrait.convert("RGB").resize((pw, ph), Image.LANCZOS), dtype=np.float32) / 255.0
    pa = np.asarray(Image.fromarray((alpha * 255).astype(np.uint8)).resize((pw, ph), Image.BILINEAR),
                    dtype=np.float32) / 255.0
    cols, rows = np.nonzero(pa.max(0) > 0.5)[0], np.nonzero(pa.max(1) > 0.5)[0]
    cx = (cols[0] + cols[-1]) / 2 if cols.size else pw / 2
    x0, y0 = round(w * (0.70 if wide else 0.5) - cx), h - ph
    head_top = y0 + (rows[0] if rows.size else 0)
    layer, A = np.zeros((h, w, 3), np.float32), np.zeros((h, w), np.float32)
    sx, sy = max(0, -x0), max(0, -y0)
    dx, dy = max(0, x0), max(0, y0)
    cw, ch = min(pw - sx, w - dx), min(ph - sy, h - dy)
    if cw > 0 and ch > 0:
        layer[dy:dy + ch, dx:dx + cw] = person[sy:sy + ch, sx:sx + cw]
        A[dy:dy + ch, dx:dx + cw] = pa[sy:sy + ch, sx:sx + cw]

    # Palavra gigante atrás da cabeça (desenhada antes de você entrar)
    word = word.upper().strip()
    if word:
        font_path = th._find_font(word)
        font, _ = th._auto_size_font(font_path, word, int(w * (0.50 if wide else 0.92)),
                                     max_size=int(h * (0.32 if wide else 0.22)), min_size=40, max_lines=1)
        img = Image.fromarray((canvas * 255).astype(np.uint8)).convert("RGBA")
        txt = Image.new("RGBA", size)
        b = font.getbbox(word)
        wy = max(head_top + h * 0.05, (b[3] - b[1]) / 2 + h * 0.03)  # topo da palavra acima da cabeça, sem sair da tela
        ImageDraw.Draw(txt).text((w * (0.70 if wide else 0.5), wy), word, font=font,
                                 fill=(*WORD_COLOR, 235), anchor="mm")
        canvas = np.asarray(Image.alpha_composite(img, txt).convert("RGB"), dtype=np.float32) / 255.0

    # Rim light: halo na cor do assunto em volta do recorte
    acc = np.array(accent, np.float32) / 255.0
    halo = np.clip(_blur(A, 10) - A, 0, 1) * 0.9
    canvas = np.clip(canvas + halo[..., None] * acc, 0, 1)
    canvas = layer * A[..., None] + canvas * (1 - A[..., None])
    edge = A * np.clip(1 - _blur(A, 4) * 1.15, 0, 1) * 0.6  # luz de contorno por dentro da borda
    canvas = np.clip(canvas + edge[..., None] * acc, 0, 1)

    # Vinheta + base escura para o texto
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    vig = 1 - 0.35 * (((xx / w - 0.5) ** 2 + (yy / h - 0.5) ** 2) / 0.5)
    start = 0.6 if wide else 0.55
    fade = np.clip((yy / h - start) / (1 - start), 0, 1) * (0.5 if wide else 0.75)
    if wide:  # o texto fica à esquerda: escurece a metade esquerda também
        fade = np.maximum(fade, np.clip((0.55 - xx / w) / 0.55, 0, 1) * 0.6)
    canvas = canvas * vig[..., None] * (1 - fade[..., None])
    out = Image.fromarray((np.clip(canvas, 0, 1) * 255).astype(np.uint8))

    _draw_text(th, out, title.upper().strip(), highlight.upper().strip(), signature, wide)
    return out


def _draw_text(th, img: Image.Image, title: str, highlight: str, signature: str, wide: bool) -> None:
    """Faixa amarela (gancho) + título branco: à esquerda no 16:9, embaixo na zona segura no 9:16."""
    w, h = img.size
    d = ImageDraw.Draw(img)
    col_w = int(w * (0.45 if wide else 0.88))
    left = int(w * 0.05) if wide else (w - col_w) // 2
    blocks = []
    if highlight:
        f, lines = th._auto_size_font(th._find_font(highlight), highlight, col_w - 40,
                                      max_size=int(h * (0.09 if wide else 0.045)), min_size=24, max_lines=1)
        blocks.append(("bar", f, lines))
    if title:
        f, lines = th._auto_size_font(th._find_font(title), title, col_w,
                                      max_size=int(h * (0.14 if wide else 0.065)), min_size=28, max_lines=3)
        blocks.append(("title", f, lines))

    def line_h(f):
        b = f.getbbox("ÁÇg")
        return b[3] - b[1]

    gap = int(h * 0.02)
    total = sum(len(ls) * int(line_h(f) * (1.6 if k == "bar" else 1.12)) for k, f, ls in blocks) + gap * len(blocks)
    y = (h - total) // 2 if wide else int(h * th.IG_SAFE_BOT) - total
    for kind, f, lines in blocks:
        lh = line_h(f)
        for line in lines:
            if kind == "bar":
                tw = f.getbbox(line)[2] - f.getbbox(line)[0]
                pad = int(lh * 0.3)
                bx = left if wide else (w - tw) // 2 - pad
                d.rectangle((bx, y, bx + tw + 2 * pad, y + int(lh * 1.6)), fill=HIGHLIGHT)
                d.text((bx + pad, y + int(lh * 0.8)), line, font=f, fill=(0, 0, 0), anchor="lm")
                y += int(lh * 1.6)
            else:
                x, anchor = (left, "lm") if wide else (w // 2, "mm")
                d.text((x, y + lh // 2), line, font=f, fill=(255, 255, 255), anchor=anchor,
                       stroke_width=max(2, lh // 18), stroke_fill=(0, 0, 0))
                y += int(lh * 1.12)
        y += gap
    if signature:
        f = th._load_font(th._find_font(signature), int(h * (0.035 if wide else 0.018)))
        top = int(h * 0.05) if wide else int(h * th.IG_SAFE_TOP) - int(h * 0.04)
        d.text((int(w * 0.04), top), signature, font=f, fill=(255, 255, 255), anchor="lm")
