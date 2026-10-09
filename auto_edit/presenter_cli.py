"""`auto-edit presenter ...` — escolhe o fundo de cada assunto e testa o recorte localmente."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from auto_edit import backdrop, presenter

presenter_app = typer.Typer(help="Fundo atrás de você por assunto (recorte local, sem conta nem API).")
console = Console()


@presenter_app.command()
def status() -> None:
    """Mostra a config e se o recorte local está pronto (onnxruntime + modelo)."""
    cfg = presenter.load_config()
    console.print(f"[bold]config:[/bold] {presenter.config_path()}")
    console.print(f"thumbnail com recorte: {'[green]ligado[/green]' if cfg.get('thumbnail') else 'desligado'}")
    console.print(f"fundo padrão: {cfg.get('default_backdrop') or '[yellow]nenhum[/yellow]'}")
    for topic, entry in (cfg.get("topics") or {}).items():
        console.print(f"  '{topic}' → {entry.get('backdrop', '-')}")
    console.print(f"temas prontos: {', '.join(backdrop.THEMES)}")
    try:
        import onnxruntime  # noqa: F401
        rt = "[green]OK[/green]"
    except ImportError:
        rt = "[yellow]falta: pip install -e \".[backdrop]\"[/yellow]"
    console.print(f"onnxruntime: {rt}")
    m = backdrop.model_path()
    console.print(f"modelo: {'[green]OK[/green] ' + str(m) if m.is_file() else '[dim]baixa na 1ª vez (107 MB)[/dim]'}")


@presenter_app.command("set")
def set_value(
    topic: Optional[str] = typer.Option(None, "--topic", help="Assunto (ex.: finanças): quando aparece no --context do vídeo, usa este fundo. Combine com --backdrop"),
    backdrop_spec: Optional[str] = typer.Option(None, "--backdrop", help="Tema pronto (finance, tech...) ou caminho de uma imagem"),
    default: Optional[str] = typer.Option(None, "--default", help="Fundo quando nenhum assunto casa"),
    thumbnail: Optional[bool] = typer.Option(None, "--thumbnail/--no-thumbnail", help="Thumbnail do long com você recortado no fundo do assunto"),
) -> None:
    """Define o fundo de um assunto, o fundo padrão e a thumbnail."""
    cfg = presenter.load_config()
    if topic:
        if not backdrop_spec:
            console.print("[red]Use --backdrop junto com --topic[/red]")
            raise typer.Exit(1)
        cfg.setdefault("topics", {})[topic] = {"backdrop": backdrop_spec}
    if default is not None:
        cfg["default_backdrop"] = default
    if thumbnail is not None:
        cfg["thumbnail"] = thumbnail
    for spec in (default, backdrop_spec):
        if spec and presenter.backdrop_file(spec) is None:
            console.print(f"[yellow]Aviso:[/yellow] '{spec}' não é um tema nem um arquivo existente")
    console.print(f"[green]✓[/green] {presenter.save_config(cfg)}")


@presenter_app.command()
def make(
    theme: str = typer.Argument(..., help=f"Tema: {', '.join(backdrop.THEMES)}"),
    out: Optional[Path] = typer.Option(None, "--out", "-o"),
) -> None:
    """Renderiza um fundo pronto (1920x1080) para você ver ou editar."""
    if theme not in backdrop.THEMES:
        console.print(f"[red]Tema inválido.[/red] Opções: {', '.join(backdrop.THEMES)}")
        raise typer.Exit(1)
    path = backdrop.make_backdrop(theme, presenter.BACKDROP_SIZE, out or Path(f"backdrop_{theme}.png"))
    console.print(f"[green]✓[/green] {path}")


@presenter_app.command()
def swap(
    media: Path = typer.Argument(..., exists=True, dir_okay=False, help="Vídeo ou imagem com você"),
    spec: str = typer.Option(..., "--backdrop", "-b", help="Tema pronto ou caminho de imagem"),
    out: Optional[Path] = typer.Option(None, "--out", "-o"),
    seconds: Optional[float] = typer.Option(None, "--seconds", "-t", help="Só os N primeiros segundos (teste rápido)"),
) -> None:
    """Troca o fundo de um vídeo/imagem (teste do recorte, sem rodar o pipeline)."""
    bd = presenter.backdrop_file(spec)
    if bd is None:
        console.print(f"[red]'{spec}' não é um tema nem um arquivo existente[/red]")
        raise typer.Exit(1)
    image = media.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
    dst = out or media.with_name(f"{media.stem}_backdrop{'.png' if image else '.mp4'}")
    try:
        if image:
            backdrop.swap_image(media, bd, dst)
        else:
            backdrop.swap_video(media, bd, dst, seconds=seconds)
    except (RuntimeError, ImportError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]✓[/green] {dst}")
