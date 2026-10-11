"""`auto-edit presenter ...` — escolhe o fundo de cada assunto e testa o recorte localmente."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console

from auto_edit import backdrop, portrait, presenter

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
        cfg.setdefault("topics", {}).setdefault(topic, {})["backdrop"] = backdrop_spec  # mantém outfit/scene
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


@presenter_app.command()
def dress(
    photo: Path = typer.Argument(..., exists=True, dir_okay=False, help="Sua foto"),
    topic: str = typer.Option(..., "--topic", help="Assunto do vídeo (finanças, política, tecnologia, educação, saúde...)"),
    n: int = typer.Option(3, "-n", min=1, max=6, help="Quantas variantes gerar"),
    out_dir: Optional[Path] = typer.Option(None, "--out-dir", "-o"),
    ref: Optional[List[Path]] = typer.Option(None, "--ref", exists=True, dir_okay=False, help="Outra foto sua (outro ângulo) só para manter o rosto; repita a opção"),
    expression: str = typer.Option("", "--expression", help="Expressão para este vídeo (ex.: 'sério, cético, uma sobrancelha levantada')"),
    scene: str = typer.Option("", "--scene", help="Cenário só deste vídeo (sobrescreve o do assunto)"),
    aspect: str = typer.Option("", "--aspect", help="16:9 ou 9:16: gera a cena de capa (tema em destaque, você integrado, espaço para o texto)"),
    elements: str = typer.Option("", "--elements", help="Elementos do tema atrás de você (ex.: 'guindastes, contêineres, torres de energia')"),
    word: str = typer.Option("", "--word", help="Palavra gigante atrás da cabeça, desenhada pelo próprio Gemini (só com --aspect)"),
    clean_scene: bool = typer.Option(False, "--clean-scene", help="A foto é uma capa de que você gostou: devolve só o cenário, sem pessoa nem texto (use no thumb --background)"),
) -> None:
    """Veste e ilumina você conforme o assunto (Gemini; o rosto não muda). Escolha a variante mais fiel."""
    if aspect and aspect not in portrait.LAYOUTS:
        console.print(f"[red]--aspect deve ser {' ou '.join(portrait.LAYOUTS)}[/red]")
        raise typer.Exit(1)
    try:
        saved = portrait.dress(photo, topic, out_dir or photo.parent, n=n, refs=ref or [],
                               expression=expression, scene=scene, aspect=aspect, elements=elements, word=word,
                               clean_scene=clean_scene)
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    for p in saved:
        console.print(f"[green]✓[/green] {p}")
    if not saved:
        raise typer.Exit(1)


@presenter_app.command()
def thumb(
    photo: Path = typer.Argument(..., exists=True, dir_okay=False, help="Foto escolhida (saída do dress)"),
    word: str = typer.Option("", "--word", "-w", help="Palavra gigante atrás da cabeça (recorte local). Vazio = cena pronta do dress --aspect: só o texto por cima"),
    title: str = typer.Option(..., "--title", help="Título branco"),
    highlight: str = typer.Option("", "--highlight", help="Gancho na faixa amarela"),
    topic: str = typer.Option("", "--topic", help="Assunto (cor da luz de contorno)"),
    video: Optional[str] = typer.Option(None, "--video", help="Nome do vídeo no workspace: salva a capa lá também"),
    signature: Optional[str] = typer.Option(None, "--signature", help="Seu nome/@ no canto (padrão: 'signature' do presenter.json)"),
    background: Optional[Path] = typer.Option(None, "--background", "-b", exists=True, dir_okay=False, help="Cenário do tema (dress --clean-scene): você entra recortado da foto, menor"),
) -> None:
    """Capa na identidade 'Autoridade Editorial' em 16:9 e 9:16."""
    from PIL import Image, ImageOps

    from auto_edit.workspace import workspace_root

    with Image.open(photo) as f:
        img = ImageOps.exif_transpose(f).convert("RGB")
    bg = None
    if background:
        with Image.open(background) as f:
            bg = f.convert("RGB")
    ref = bg or img  # o formato da capa vem do cenário quando há um
    sizes = portrait.SIZES
    name = min(sizes, key=lambda k: abs(sizes[k][0] / sizes[k][1] - ref.width / ref.height))
    if bg is not None and not word:
        console.print("[red]--background precisa de --word (o recorte é que põe você no cenário)[/red]")
        raise typer.Exit(1)
    if not word or abs(sizes[name][0] / sizes[name][1] - ref.width / ref.height) < 0.03:
        sizes = {name: sizes[name]}  # cena pronta: só o formato dela (cortar 16:9 em 9:16 tiraria o tema)
    alpha = None
    if word:
        try:
            alpha = portrait.matte(img)
        except (RuntimeError, ImportError) as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)
    sig = signature if signature is not None else presenter.load_config().get("signature", "")
    accent = portrait.topic_style(topic)["accent"]
    outs = {}
    for name, size in sizes.items():
        out = photo.with_name(f"{photo.stem}_{name}.png")
        portrait.compose(img, alpha, size, word, title, highlight, accent, sig, background=bg).save(out, "PNG")
        outs[name] = out
        console.print(f"[green]✓[/green] {out}")
    if video:
        ws = workspace_root() / video
        pipeline = ws / "pipeline.json"
        kind = "16x9"
        if pipeline.is_file():
            import json
            kind = "16x9" if json.loads(pipeline.read_text(encoding="utf-8")).get("type") == "long" else "9x16"
        if kind not in outs:
            console.print(f"[yellow]Este vídeo usa capa {kind}: rode o thumb com a cena nesse formato[/yellow]")
            raise typer.Exit(1)
        for dst in (workspace_root() / "output" / f"{video}_thumbnail.png", ws / "thumbnail_custom.png"):
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(outs[kind].read_bytes())
            console.print(f"[green]✓[/green] {dst}")
        console.print("Capa no 1º quadro do vídeo: auto-edit resume <vídeo> --from thumbnail")
