"""`auto-edit cover ...` — capa em motion graphics com fotos do assunto (Openverse): buscar opções e montar."""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console

from auto_edit import cover
from auto_edit.workspace import workspace_root

cover_app = typer.Typer(help="Capa do vídeo em motion graphics, só com as informações do vídeo (sem você).")
console = Console()

FORMATS = {"9:16": ((1080, 1920), (1080, 1920)), "16:9": ((1920, 1080), (1280, 720))}  # (animação, thumbnail)


def _format(ws: Path, fmt: Optional[str]) -> str:
    """9:16 para short, 16:9 para long (pelo pipeline.json); --format decide quando o vídeo ainda não existe."""
    if fmt:
        if fmt not in FORMATS:
            console.print(f"[red]--format deve ser {' ou '.join(FORMATS)}[/red]")
            raise typer.Exit(1)
        return fmt
    try:
        return "16:9" if json.loads((ws / "pipeline.json").read_text(encoding="utf-8")).get("type") == "long" else "9:16"
    except (OSError, ValueError):
        return "9:16"


def _metadata(ws: Path) -> dict:
    try:
        return json.loads((ws / "metadata.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


@cover_app.command()
def search(
    name: str = typer.Argument(..., help="Nome do vídeo no workspace (a pasta é criada se ainda não existir)"),
    query: Optional[List[str]] = typer.Option(None, "--query", "-q", help="Busca em inglês; repita (padrão: image_queries do metadata)"),
    n: int = typer.Option(4, "-n", min=1, max=8, help="Opções por busca"),
    fmt: Optional[str] = typer.Option(None, "--format", help="9:16 ou 16:9"),
) -> None:
    """Baixa opções de fotos do assunto e monta uma folha numerada para escolher."""
    ws = workspace_root() / name
    queries = query or cover.from_metadata(_metadata(ws))["queries"]
    if not queries:
        console.print("[red]Sem buscas: use -q (ex.: -q \"container port cranes\")[/red]")
        raise typer.Exit(1)
    cdir = cover.cover_dir(ws)
    orient = cover.orientation(FORMATS[_format(ws, fmt)][0])
    try:
        found = cover.fetch(queries, cdir / "options", orient, per_query=n)
    except (RuntimeError, OSError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    options = [p for paths in found for p in paths]
    if not options:
        console.print("[red]Nenhuma foto encontrada: tente buscas mais concretas[/red]")
        raise typer.Exit(1)
    (cdir / "options.json").write_text(json.dumps([p.relative_to(cdir).as_posix() for p in options]), encoding="utf-8")
    sheet = cover.contact_sheet(options, cdir / "opcoes.png")
    for i, (q, paths) in enumerate(zip(queries, found)):
        first = sum(len(p) for p in found[:i]) + 1
        console.print(f"{first}–{first + len(paths) - 1}: {q}")
    console.print(f"[green]✓[/green] {sheet}  → escolha com: auto-edit cover make \"{name}\" --pick 1,5,9")


@cover_app.command()
def make(
    name: str = typer.Argument(..., help="Nome do vídeo no workspace"),
    pick: str = typer.Option(..., "--pick", help="Números da folha: fundo, cartão 1, cartão 2 (ex.: 2,5,9)"),
    word: Optional[str] = typer.Option(None, "--word", help="Palavra gigante"),
    title: Optional[str] = typer.Option(None, "--title", help="Título branco"),
    highlight: Optional[str] = typer.Option(None, "--highlight", help="Gancho na faixa amarela"),
    signature: Optional[str] = typer.Option(None, "--signature", help="Seu nome/@ no canto"),
    fmt: Optional[str] = typer.Option(None, "--format", help="9:16 ou 16:9"),
) -> None:
    """Monta a capa (thumbnail + abertura animada) e salva onde o pipeline usa."""
    ws = workspace_root() / name
    cdir = cover.cover_dir(ws)
    try:
        options = json.loads((cdir / "options.json").read_text(encoding="utf-8"))
        chosen = [options[int(i) - 1] for i in pick.split(",") if i.strip()]
    except (OSError, ValueError, IndexError):
        console.print(f"[red]Rode antes `auto-edit cover search \"{name}\"` e use números da folha[/red]")
        raise typer.Exit(1)
    data = cover.load(ws) or cover.from_metadata(_metadata(ws))
    for key, value in (("word", word), ("title", title), ("highlight", highlight), ("signature", signature)):
        if value is not None:
            data[key] = value
    data["images"] = chosen
    cover.save(ws, data)
    anim_size, thumb_size = FORMATS[_format(ws, fmt)]
    try:
        mov = cover.render(data, [cdir / c for c in chosen], anim_size, cdir)
        png = cover.first_frame(mov, cdir / "capa.png", thumb_size)
        hook = cover.preview(mov, cdir / "abertura.mp4")
    except (RuntimeError, OSError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    for p in (png, hook, *cover.publish_png(png, ws, name, workspace_root() / "output")):
        console.print(f"[green]✓[/green] {p}")
