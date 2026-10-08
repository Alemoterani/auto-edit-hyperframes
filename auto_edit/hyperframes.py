"""
HyperFrames renderer: turns an HTML template in <repo>/hyperframes/ into a
transparent ProRes 4444 .mov (alpha) that the overlay/caption stages composite
with FFmpeg. Rendering runs locally (headless Chrome + FFmpeg via `npx hyperframes`).

A template is a folder with an index.html that reads ``window.AE_DATA`` from a
``data.js`` next to it. HyperFrames reads the root's data-duration/width/height
before any script runs, so those are rewritten in a per-render copy instead.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from auto_edit import overlay_assets

TEMPLATES_DIR = overlay_assets.default_repo_root() / "hyperframes"
VENDOR_CLI_PACKAGE = overlay_assets.default_repo_root() / "vendor" / "hyperframes" / "packages" / "cli" / "package.json"


def package_spec() -> str:
    """`hyperframes@<version>` pinned to the source in vendor/hyperframes, so the
    renderer always matches the bundled code; plain `hyperframes` if it's absent."""
    try:
        version = json.loads(VENDOR_CLI_PACKAGE.read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError, KeyError):
        return "hyperframes"
    return f"hyperframes@{version}"


def npx() -> str | None:
    """Path to npx (npx.cmd on Windows), or None if Node isn't installed."""
    return shutil.which("npx")


def template_dir(name: str) -> Path:
    """`lower_third` -> <repo>/hyperframes/overlays/lower_third; `captions` -> <repo>/hyperframes/captions."""
    for d in (TEMPLATES_DIR / "overlays" / name, TEMPLATES_DIR / name):
        if (d / "index.html").is_file():
            return d
    raise FileNotFoundError(f"HyperFrames template not found: {name} (looked in {TEMPLATES_DIR})")


def _patch_root(html: str, width: int, height: int, duration: float) -> str:
    """Rewrite the composition root's size/duration (first occurrence = root div)."""
    html = re.sub(r'data-duration="[^"]*"', f'data-duration="{duration:.3f}"', html, count=1)
    html = re.sub(r'data-width="[^"]*"', f'data-width="{width}"', html, count=1)
    html = re.sub(r'data-height="[^"]*"', f'data-height="{height}"', html, count=1)
    # The root CSS box is authored in px; override it to the real frame size.
    return html.replace("</head>", f"<style>#root{{width:{width}px;height:{height}px}}</style></head>", 1)


def render(
    template: str,
    data: dict,
    out_dir: Path,
    width: int,
    height: int,
    duration: float,
    fps: str | None = None,
) -> Path:
    """Render `template` with `data` to <out_dir>/<hash>.mov and return its path.

    Identical inputs reuse the cached file, so `resume` doesn't re-render.
    Raises RuntimeError if npx is missing or the render fails.
    """
    src = template_dir(template)
    html = _patch_root((src / "index.html").read_text(encoding="utf-8"), width, height, duration)
    data_js = f"window.AE_DATA = {json.dumps(data, ensure_ascii=False)};\n"

    key = hashlib.sha256(f"{html}\0{data_js}\0{fps}".encode("utf-8")).hexdigest()[:16]
    out_dir.mkdir(parents=True, exist_ok=True)
    output = out_dir / f"{template}-{key}.mov"
    if output.is_file() and output.stat().st_size > 0:
        print(f"[hyperframes] cache hit: {output.name}")
        return output

    npx_bin = npx()
    if npx_bin is None:
        raise RuntimeError("npx not found — install Node.js 22+ to render HyperFrames templates")

    with tempfile.TemporaryDirectory(prefix="hf-") as tmp:
        project = Path(tmp) / template
        shutil.copytree(src, project)
        (project / "index.html").write_text(html, encoding="utf-8")
        (project / "data.js").write_text(data_js, encoding="utf-8")
        cmd = [npx_bin, "-y", package_spec(), "render", str(project),
               "--format", "mov", "--quiet", "-o", str(output)]
        if fps:
            cmd += ["--fps", fps]
        print(f"[hyperframes] rendering '{template}' {width}x{height} {duration:.1f}s ...")
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0 or not output.is_file():
        tail = "\n".join((result.stderr or result.stdout or "").strip().splitlines()[-15:])
        raise RuntimeError(f"hyperframes render failed for '{template}':\n{tail}")
    return output
