"""
Capa do vídeo em motion graphics, sem o apresentador (template ``hyperframes/cover``).

O quadro 0 da animação é a thumbnail; a animação inteira (~2,5 s) abre o vídeo como gancho. Por vídeo mudam só as
fotos do assunto (Openverse, domínio público, ``auto_edit/stock.py``), a palavra gigante, a faixa amarela, o título e a cor de brilho.

Os dados ficam em ``<workspace>/cover/cover.json`` (``auto-edit cover make``); sem ele, o stage ``thumbnail`` monta
tudo do ``metadata.json`` com a 1ª foto de cada busca.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from auto_edit import hyperframes, overlay_assets, stock

HOOK_SECONDS = 2.5
DIR = "cover"
DEFAULT_ACCENT = "#5aa0ff"


def cover_dir(workspace: Path) -> Path:
    return workspace / DIR


def load(workspace: Path) -> dict | None:
    p = cover_dir(workspace) / "cover.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None
    except (OSError, json.JSONDecodeError):
        return None


def save(workspace: Path, data: dict) -> Path:
    p = cover_dir(workspace) / "cover.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def accent_for(template: str | None) -> str:
    """Cor de brilho do tipo de conteúdo (``assets/thumbnails/templates.json``) em hex."""
    try:
        reg = json.loads((overlay_assets.default_repo_root() / "assets" / "thumbnails" / "templates.json")
                         .read_text(encoding="utf-8"))
        rgb = reg["templates"][template or reg["default"]]["accent"]
        return "#{:02x}{:02x}{:02x}".format(*rgb)
    except (OSError, ValueError, KeyError, TypeError):
        return DEFAULT_ACCENT


def from_metadata(metadata: dict) -> dict:
    """Dados da capa a partir do ``thumbnail`` que o agente de metadata escreve."""
    t = metadata.get("thumbnail") or {}
    return {
        "word": t.get("word", ""),
        "title": t.get("main_text", ""),
        "highlight": t.get("sub_text") or "",
        "queries": t.get("image_queries") or [],
        "accent": accent_for(t.get("template")),
        "images": [],
    }


def orientation(size: tuple[int, int]) -> str:
    return "landscape" if size[0] >= size[1] else "portrait"


def fetch(queries: list[str], dest: Path, orient: str, per_query: int = 1) -> list[list[Path]]:
    """Baixa ``per_query`` fotos por busca em ``dest``; devolve uma lista de arquivos por busca. A 1ª busca é o
    fundo (no formato da capa); as outras viram os cartões, que são horizontais nos dois formatos."""
    found = []
    for qi, q in enumerate(queries, 1):
        paths = []
        for pi, photo in enumerate(stock.search(q, orient if qi == 1 else "landscape", per_query), 1):
            paths.append(stock.download(photo["url"], dest / f"q{qi}_{pi}.jpg"))
        found.append(paths)
    return found


def contact_sheet(options: list[Path], out: Path, thumb: int = 360) -> Path:
    """Folha com as opções numeradas (1, 2, 3...) para escolher com ``--pick``."""
    cols = 4
    rows = (len(options) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * thumb, max(1, rows) * thumb), (18, 18, 22))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("arialbd.ttf", 44)
    except OSError:
        font = ImageFont.load_default(size=44)
    for i, p in enumerate(options):
        with Image.open(p) as im:
            tile = im.convert("RGB")
        tile.thumbnail((thumb - 8, thumb - 8))
        x, y = (i % cols) * thumb, (i // cols) * thumb
        sheet.paste(tile, (x + (thumb - tile.width) // 2, y + (thumb - tile.height) // 2))
        draw.rectangle((x + 6, y + 6, x + 70, y + 60), fill=(255, 212, 0))
        draw.text((x + 38, y + 33), str(i + 1), font=font, fill=(0, 0, 0), anchor="mm")
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out


def render(data: dict, images: list[Path], size: tuple[int, int], out_dir: Path) -> Path:
    """Renderiza a animação da capa (``.mov`` com alpha) no tamanho ``size``."""
    files = {f"img{i}{Path(p).suffix.lower() or '.jpg'}": Path(p) for i, p in enumerate(images[:3])}
    payload = {k: data.get(k, "") for k in ("word", "title", "highlight", "signature")}
    payload.update(accent=data.get("accent") or DEFAULT_ACCENT, images=list(files))
    return hyperframes.render("cover", payload, out_dir, size[0], size[1], HOOK_SECONDS, files=files)


def first_frame(mov: Path, out: Path, size: tuple[int, int]) -> Path:
    """Quadro 0 da animação = a thumbnail, no tamanho da plataforma."""
    w, h = size
    subprocess.run(["ffmpeg", "-y", "-i", str(mov), "-frames:v", "1",
                    "-vf", f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}", str(out)],
                   capture_output=True, check=True)
    return out


def preview(mov: Path, out: Path) -> Path:
    """MP4 da animação para ver no celular/navegador (o fundo transparente vira preto)."""
    subprocess.run(["ffmpeg", "-y", "-i", str(mov), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-crf", "18", str(out)], capture_output=True, check=True)
    return out


def publish_png(png: Path, workspace: Path, name: str, output_dir: Path) -> list[Path]:
    """Capa pronta nos dois lugares que o pipeline usa: ``thumbnail_custom.png`` e ``output/<nome>_thumbnail.png``."""
    dsts = [workspace / "thumbnail_custom.png", output_dir / f"{name}_thumbnail.png"]
    for d in dsts:
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(png, d)
    return dsts
