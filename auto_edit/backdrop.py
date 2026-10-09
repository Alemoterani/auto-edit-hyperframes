"""
Fundo por assunto: recorta a pessoa do vídeo (Robust Video Matting, ONNX — GPU via DirectML no
Windows, senão CPU) e põe atrás dela um cenário que combina com o assunto. 100% local, sem conta
e sem API.

Modelo: rvm_resnet50_fp32.onnx (107 MB, GPL-3.0, PeterL1n/RobustVideoMatting v1.0.0), baixado uma
vez para ``~/.auto-edit/models/``. Escolhido no lugar do mobilenet (15 MB) depois de um teste real:
não deixa vazar objetos do fundo encostados no corpo (uma cama nos cantos de baixo do quadro) e
mantém sólidas as mãos borradas pelo movimento, com praticamente a mesma velocidade numa GTX 1050 Ti.

    auto-edit presenter swap clip.mp4 -b finance -t 5   # teste rápido
    auto-edit long video.mp4 -c "finanças" --backdrop   # no pipeline, logo depois do execute
    python -m auto_edit.backdrop <workspace>            # o gancho em si (precisa de pipeline["backdrop"])

Precisa do extra ``[backdrop]`` (onnxruntime-directml no Windows, onnxruntime nos outros sistemas).
A pessoa continua com a roupa que vestiu na gravação: isto troca o *cenário*, não muda a pessoa.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from urllib.request import urlretrieve

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from auto_edit import config, probe

MODEL_URL = "https://github.com/PeterL1n/RobustVideoMatting/releases/download/v1.0.0/rvm_resnet50_fp32.onnx"
MATTE_WIDTH = 768  # os quadros são recortados nesta largura e o alpha volta ampliado (velocidade x detalhe na borda)
RATIO = 0.375      # downsample_ratio do RVM: a rede enxerga ~MATTE_WIDTH*RATIO px e um filtro guiado recupera a borda
# O RVM é recorrente: num quadro isolado (thumbnail, primeiro quadro do clipe) uma passada só deixa o
# tronco meio transparente. Repetir o quadro deixa o estado assentar — medido num clipe real de selfie:
# de 6,3% para 1,8% de pixels semitransparentes com 4 passadas.
WARMUP = 4

# nome -> (topo, base, destaque) em RGB dos fundos gerados por código
THEMES = {
    "finance": ((8, 24, 48), (20, 60, 90), (90, 200, 160)),
    "tech": ((10, 8, 30), (30, 10, 70), (0, 220, 255)),
    "education": ((250, 245, 235), (225, 215, 195), (200, 120, 40)),
    "health": ((230, 245, 240), (190, 225, 215), (40, 160, 130)),
    "neutral": ((40, 40, 46), (22, 22, 26), (200, 200, 210)),
}


def model_path() -> Path:
    return config.home_dir() / "models" / "rvm_resnet50_fp32.onnx"


def ensure_model() -> Path:
    p = model_path()
    if not p.is_file() or p.stat().st_size == 0:
        p.parent.mkdir(parents=True, exist_ok=True)
        print(f"[backdrop] downloading matting model (107 MB, once) → {p}")
        urlretrieve(MODEL_URL, p)  # noqa: S310 — URL https fixa do release oficial
    return p


def make_backdrop(theme: str, size: tuple[int, int], out: Path) -> Path:
    """Fundo de estúdio gerado por código: degradê vertical + manchas de luz suaves + grade discreta."""
    top, bottom, accent = THEMES[theme]
    w, h = size
    t = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    grad = (np.array(top, np.float32) * (1 - t) + np.array(bottom, np.float32) * t)
    base = np.repeat(grad, w, axis=1)
    glow = Image.new("RGB", (w, h), (0, 0, 0))
    d = ImageDraw.Draw(glow)
    for cx, cy, r in ((0.15, 0.25, 0.30), (0.85, 0.7, 0.35), (0.6, 0.1, 0.2)):
        d.ellipse([(cx - r) * w, (cy - r) * h, (cx + r) * w, (cy + r) * h], fill=accent)
    glow = glow.filter(ImageFilter.GaussianBlur(min(w, h) * 0.22))
    img = Image.fromarray(np.maximum(base, np.asarray(glow, np.float32) * 0.45).astype(np.uint8), "RGB")
    d = ImageDraw.Draw(img, "RGBA")
    step = max(w // 24, 24)
    for x in range(0, w, step):
        d.line([(x, 0), (x, h)], fill=(*accent, 14))
    for y in range(0, h, step):
        d.line([(0, y), (w, y)], fill=(*accent, 14))
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG")
    return out


def cover(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Redimensiona e corta no centro ``img`` para ficar exatamente com ``size`` (sem distorcer)."""
    w, h = size
    s = max(w / img.width, h / img.height)
    r = img.resize((max(w, round(img.width * s)), max(h, round(img.height * s))), Image.LANCZOS)
    x, y = (r.width - w) // 2, (r.height - h) // 2
    return r.crop((x, y, x + w, y + h))


class Matter:
    """RVM com o estado recorrente; chame em quadros seguidos de UM clipe (``reset`` entre clipes)."""

    def __init__(self, session=None):
        if session is None:
            import onnxruntime as ort  # import tardio: dependência opcional
            wanted = ("DmlExecutionProvider", "CPUExecutionProvider")  # GPU via DirectML quando instalado
            session = ort.InferenceSession(
                str(ensure_model()), providers=[p for p in wanted if p in ort.get_available_providers()])
        self.session = session
        self.reset()

    def reset(self) -> None:
        self.state = [np.zeros((1, 1, 1, 1), np.float32) for _ in range(4)]

    def matte(self, small: np.ndarray) -> np.ndarray:
        """``small``: RGB hxwx3 uint8 (já no tamanho do recorte) -> alpha hxw uint8, do mesmo tamanho."""
        feed = {"src": (small.astype(np.float32) / 255.0).transpose(2, 0, 1)[None],
                "downsample_ratio": np.array([RATIO], np.float32)}
        feed.update({f"r{i + 1}i": st for i, st in enumerate(self.state)})
        out = self.session.run(None, feed)
        self.state = list(out[2:6])
        return (np.clip(out[1][0, 0], 0, 1) * 255).astype(np.uint8)

    def alpha(self, frame: np.ndarray) -> np.ndarray:
        """``frame``: RGB HxWx3 uint8 -> alpha HxW float32 em [0, 1], no tamanho do quadro."""
        h, w = frame.shape[:2]
        mw, mh = matte_size(w, h)
        small = np.asarray(Image.fromarray(frame).resize((mw, mh), Image.BILINEAR))
        pha = self.matte(small)
        if (mw, mh) != (w, h):
            pha = np.asarray(Image.fromarray(pha).resize((w, h), Image.BILINEAR))
        return pha.astype(np.float32) / 255.0


def matte_size(w: int, h: int) -> tuple[int, int]:
    mw = min(MATTE_WIDTH, w) // 2 * 2
    return mw, max(2, round(h * mw / w) // 2 * 2)


def composite(frame: np.ndarray, alpha: np.ndarray, bg: np.ndarray) -> np.ndarray:
    a = alpha[..., None]
    return (frame * a + bg * (1 - a)).astype(np.uint8)


def swap_image(src: Path, backdrop: Path, out: Path, matter: Matter | None = None) -> Path:
    """Versão de um quadro só (thumbnails): a pessoa de ``src`` sobre ``backdrop``."""
    with Image.open(src) as f:
        frame = np.asarray(f.convert("RGB"))
    with Image.open(backdrop) as b:
        bg = np.asarray(cover(b.convert("RGB"), (frame.shape[1], frame.shape[0])))
    matter = matter or Matter()
    matter.reset()
    for _ in range(WARMUP):
        alpha = matter.alpha(frame)
    Image.fromarray(composite(frame, alpha, bg)).save(out, "PNG")
    return out


def swap_video(src: Path, backdrop: Path, dst: Path, matter: Matter | None = None, ffmpeg: str = "ffmpeg",
               seconds: float | None = None) -> Path:
    """Renderiza ``src`` de novo com ``backdrop`` atrás da pessoa; o áudio é copiado sem alteração.

    O Python recorta uma cópia pequena decodificada (o alpha sai como vídeo em tons de cinza); o
    FFmpeg amplia esse alpha e faz a composição na resolução cheia. ``seconds`` limita a saída aos
    N primeiros segundos (teste rápido).
    """
    w, h, fps = probe.video_specs(src)
    fps = fps or "30"
    mw, mh = matte_size(w, h)
    limit = ["-t", str(seconds)] if seconds else []
    with Image.open(backdrop) as b:
        bg_png = dst.with_suffix(".bg.png")
        cover(b.convert("RGB"), (w, h)).save(bg_png, "PNG")
    matter = matter or Matter()
    dec = subprocess.Popen(
        [ffmpeg, "-v", "error", *limit, "-i", str(src), "-vf", f"fps={fps},scale={mw}:{mh}",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    graph = (f"[0:v]fps={fps}[v];[1:v]scale={w}:{h}:flags=bicubic[a];[v][a]alphamerge[fg];"
             f"[2:v]scale={w}:{h}[bg];[bg][fg]overlay=shortest=1:format=auto,format=yuv420p[out]")
    enc = subprocess.Popen(
        [ffmpeg, "-y", "-v", "error", *limit, "-i", str(src),
         "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{mw}x{mh}", "-r", fps, "-i", "-",
         "-loop", "1", "-framerate", fps, "-i", str(bg_png),
         "-filter_complex", graph, "-map", "[out]", "-map", "0:a?", "-c:v", "libx264", "-crf", "18",
         "-preset", "fast", "-c:a", "copy", "-movflags", "+faststart", str(dst)],
        # sem -shortest: o overlay=shortest já encerra o vídeo junto com o corte; o -shortest cortava os últimos quadros
        stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    size = mw * mh * 3
    n = 0
    try:
        while True:
            raw = dec.stdout.read(size)
            if len(raw) < size:
                break
            small = np.frombuffer(raw, np.uint8).reshape(mh, mw, 3)
            if n == 0:
                for _ in range(WARMUP - 1):
                    matter.matte(small)  # assenta o estado recorrente no primeiro quadro
            enc.stdin.write(matter.matte(small).tobytes())
            n += 1
            if n % 150 == 0:
                print(f"[backdrop] {n} frames")
    finally:
        enc.stdin.close()
        dec.stdout.close()
        dec.wait()
        enc.wait()
        bg_png.unlink(missing_ok=True)
    if enc.returncode != 0 or n == 0:
        raise RuntimeError(f"backdrop render failed (ffmpeg exit {enc.returncode}, {n} frames)")
    return dst


def run_for_workspace(workspace: Path) -> bool:
    """Gancho do pipeline: troca o fundo do ``edited_video.mp4`` no próprio arquivo (o corte fica
    guardado em ``edited_video_original.mp4``). Roda logo depois de o executor gravar um corte novo.

    Fica desligado, a menos que o ``pipeline.json`` tenha ``backdrop: true``. Nunca levanta exceção:
    em qualquer falha o corte fica intocado, como nos auxiliares de cold open e de abertura.
    """
    from auto_edit import pipeline as pl, presenter

    edited = workspace / "edited_video.mp4"
    original = workspace / "edited_video_original.mp4"
    swapped = workspace / "edited_video.backdrop.mp4"
    marker = workspace / "backdrop.done"
    try:
        if not pl.load(workspace).get("backdrop") or not edited.is_file():
            return False
        if marker.is_file() and marker.read_text() == str(edited.stat().st_mtime_ns):
            return False  # este corte já foi trocado (o gancho rodou duas vezes sem um execute novo)
        bd = presenter.resolve_backdrop(pl.load(workspace).get("context", ""))
        if bd is None:
            print("[backdrop] no backdrop for this context (auto-edit presenter set --topic ...) — skipping")
            return False
        print(f"[backdrop] {bd.name} behind the presenter")
        # O render leva minutos: o corte só é substituído quando ele termina, então uma execução
        # interrompida nunca deixa um edited_video.mp4 pela metade para o `resume` usar.
        swap_video(edited, bd, swapped)
        edited.replace(original)
        swapped.replace(edited)
        marker.write_text(str(edited.stat().st_mtime_ns))
        return True
    except Exception as e:
        print(f"[backdrop] skipped: {e}")
        swapped.unlink(missing_ok=True)
        return False


if __name__ == "__main__":
    run_for_workspace(Path(sys.argv[1]))
