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

DEFAULT_MODEL = "gemini-3-pro-image"  # o flash deixava o rosto com cara de IA; AUTO_EDIT_IMAGE_MODEL troca
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
    "Keep the person's identity EXACTLY as in the photos: same face shape, eyes, nose, mouth, skin tone, hairline, "
    "hair and facial hair style, and age. Do not slim, reshape, de-age or change identity in any way."
)
# Cena de capa (dress --aspect): como nas referências, o TEMA é o protagonista e você é um elemento dele
LAYOUTS = {
    "16:9": (
        "Wide 16:9 YouTube thumbnail scene. The THEME is the hero, not the person: the theme elements fill the "
        "frame, bold, dramatic and readable at small size. The person is a supporting element on the right third, "
        "waist-up, about 55% of the frame height, cut by the bottom edge. Keep the left 45% of the frame darker and "
        "calmer (no faces, no busy detail) for a headline added later."
    ),
    "9:16": (
        "Vertical 9:16 thumbnail scene. The THEME is the hero, not the person: the theme elements fill the upper two "
        "thirds, bold, dramatic and readable at small size. The person is a supporting element, centered, waist-up, "
        "about 45% of the frame height, cut by the bottom edge. Keep the bottom 30% darker and calmer for a headline "
        "added later."
    ),
}
INTEGRATE = (
    "Integrate the person completely into the scene: same light, haze and color grade, partly in shadow, never "
    "brighter, sharper or more saturated than the theme elements; the eye goes to the theme first, then to him."
)
# Luz: a pessoa recebe a MESMA luz da cena (senão fica "colada" por cima do fundo)
RELIGHT = (
    "Relight the person so they truly belong in the scene, as if photographed on location with one camera: "
    "light direction, color temperature and intensity come from the scene's own light sources; a rim/back light "
    "from the brightest area of the background on hair, ears and shoulders; ambient fill tinted by the environment; "
    "a soft, motivated key light on the face that is never brighter than the scene allows. Match contrast, black "
    "levels, haze, grain and sharpness between person and background; one cinematic color grade on the whole image."
)
PHOTO = (
    "It must look like a real photograph, not CGI: full-frame camera, 85mm lens at f/1.8, natural light, crisp focus "
    "on the eyes, realistic skin texture and micro-detail, natural creamy bokeh, no plastic or airbrushed look."
)
RETOUCH = (
    "Professional retouch: remove blemishes, redness, oily shine and uneven tone while keeping real skin texture "
    "and pores. Groom the beard and mustache in the same style and length: clean sharp cheek and neck lines, "
    "even density, no stray hairs."
)
REFS_NOTE = (
    "The first image is the photo to edit. The other images are the same person from other angles: "
    "use them only as identity reference so the face stays identical."
)


def topic_style(topic: str) -> dict:
    """Roupa, cenário e cor do assunto: a config do presenter sobrescreve o padrão; assunto desconhecido = neutro."""
    t = (topic or "").lower()
    base = next((v for k, v in TOPICS.items() if k in t), TOPICS["neutro"])
    user = next((v for k, v in (presenter.load_config().get("topics") or {}).items() if k.lower() in t), {})
    style = {**base, **{k: user[k] for k in ("outfit", "scene", "accent") if user.get(k)}}
    style["accent"] = tuple(style["accent"])
    return style


def build_prompt(topic: str, expression: str = "", scene: str = "", refs: int = 0,
                 aspect: str = "", elements: str = "", word: str = "") -> str:
    """Prompt da edição. ``expression``/``scene``/``elements``/``word`` valem só para este vídeo; ``refs`` = fotos
    extras de identidade; ``aspect`` (16:9 ou 9:16) troca o retrato por uma cena de capa onde o tema domina."""
    s = topic_style(topic)
    notes = presenter.load_config().get("identity", "")  # traços seus que o modelo costuma "arrumar" (entradas, textura)
    face = (f"Change the facial expression to: {expression}, with the same facial features. "
            if expression else "Keep the same facial expression. ")
    who = f"{REFS_NOTE + ' ' if refs else ''}{IDENTITY_RULES} {notes + ' ' if notes else ''}{face}"
    wear = f"Clothing: {s['outfit']}, conveying authority. "
    if aspect in LAYOUTS:
        text = (f'Behind the person\'s head, huge bold condensed off-white letters spelling exactly "{word}", '
                "partially hidden by the head, lit and graded like the scene. No other text, no logos."
                if word else "No text, no logos.")
        return (
            f"Create a photorealistic thumbnail scene featuring this person. {LAYOUTS[aspect]} "
            f"{'Theme elements: ' + elements + '. ' if elements else ''}Setting: {scene or s['scene']}. "
            f"{who}{wear}{INTEGRATE} {RELIGHT} {PHOTO} {RETOUCH} {text}"
        )
    return (
        "Edit this photo into a professional, photorealistic portrait. Keep the same head pose and framing. "
        f"{who}{wear}Background: {scene or s['scene']}, shallow depth of field. "
        f"{RELIGHT} {PHOTO} {RETOUCH} No text, no logos, no artificial filters."
    )


def _client():
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("Defina GEMINI_API_KEY para trocar roupa/cenário")
    try:  # HTTPS pelos certificados do Windows (antivírus/proxy que inspeciona TLS quebra o bundle do certifi)
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        pass
    try:
        from google import genai  # import tardio: dependência opcional (extra backdrop)
    except ImportError:
        raise RuntimeError('Falta o google-genai: pip install -e ".[backdrop]"') from None
    return genai.Client(api_key=key)


def _open(path: Path) -> Image.Image:
    with Image.open(path) as f:
        return ImageOps.exif_transpose(f).convert("RGB")  # foto de celular vem deitada sem isso


def dress(photo: Path, topic: str, out_dir: Path, n: int = 3, client=None, refs: list[Path] = (),
          expression: str = "", scene: str = "", aspect: str = "", elements: str = "",
          word: str = "") -> list[Path]:
    """Gera ``n`` variantes da foto vestida/iluminada para o assunto. ``refs``: outras fotos suas (outros
    ângulos) que só servem para o modelo manter o rosto. Com ``aspect``, sai a cena de capa já no formato.
    Devolve os PNGs salvos."""
    client = client or _client()
    images = [_open(photo), *(_open(r) for r in refs)]  # o google-genai aceita a imagem PIL direto
    contents = [*images, build_prompt(topic, expression, scene, len(refs), aspect, elements, word)]
    extra = {"config": {"response_modalities": ["IMAGE"], "image_config": {"aspect_ratio": aspect}}} if aspect else {}
    model = os.environ.get("AUTO_EDIT_IMAGE_MODEL", DEFAULT_MODEL)
    slug = (topic or "neutro").split()[0].lower() + (f"_{aspect.replace(':', 'x')}" if aspect else "")
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for i in range(1, n + 1):
        resp = client.models.generate_content(model=model, contents=contents, **extra)
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
    portrait: Image.Image, alpha: np.ndarray | None, size: tuple[int, int], word: str, title: str,
    highlight: str = "", accent: tuple[int, int, int] = (255, 255, 255), signature: str = "",
) -> Image.Image:
    """Capa no layout da identidade: 16:9 você à direita e texto à esquerda; 9:16 você no centro e texto embaixo.
    ``alpha`` None = cena pronta do ``dress --aspect`` (você já integrado ao tema): só vinheta e tipografia."""
    th = _thumb()
    if alpha is None:
        return _finish(th, np.asarray(backdrop.cover(portrait.convert("RGB"), size), np.float32) / 255.0,
                       title, highlight, signature)
    w, h = size
    wide = w > h
    src = np.asarray(portrait.convert("RGB"), dtype=np.float32) / 255.0

    # Fundo: o cenário da foto sem você, desfocado, sem escurecer só ele (senão você fica colado por cima)
    plate = _clean_plate(src, alpha, max(src.shape[:2]) / 25)
    bg = backdrop.cover(Image.fromarray((plate * 255).astype(np.uint8)), size).filter(ImageFilter.GaussianBlur(6))
    canvas = np.asarray(bg, dtype=np.float32) / 255.0  # mesma luz da foto: você e o cenário recebem o mesmo tratamento

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
    halo = np.clip(_blur(A, 10) - A, 0, 1) * 0.3  # sutil: forte demais te descola do fundo
    canvas = np.clip(canvas + halo[..., None] * acc, 0, 1)
    canvas = layer * A[..., None] + canvas * (1 - A[..., None])
    edge = A * np.clip(1 - _blur(A, 4) * 1.15, 0, 1) * 0.2  # luz de contorno por dentro da borda
    canvas = np.clip(canvas + edge[..., None] * acc, 0, 1)
    return _finish(th, canvas, title, highlight, signature)


def _finish(th, canvas: np.ndarray, title: str, highlight: str, signature: str) -> Image.Image:
    """Vinheta + base escura onde vai o texto, e a tipografia da marca por cima."""
    h, w = canvas.shape[:2]
    wide = w > h
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
