"""
Presenter: qual fundo vai atrás de você em cada assunto. Só local (veja ``backdrop.py``).

A config fica em ``~/.auto-edit/presenter.json`` (fora do repo, como o perfil do criador):

    {
      "thumbnail": true,                 # thumbnail do long = melhor quadro, você recortado, no fundo do assunto
      "default_backdrop": "neutral",
      "topics": {                        # vale o primeiro assunto encontrado no --context do vídeo
        "finanças":   {"backdrop": "finance"},                 # tema pronto ...
        "tecnologia": {"backdrop": "tech"},
        "viagem":     {"backdrop": "C:/fotos/praia.jpg"}       # ... ou qualquer imagem sua
      }
    }

Temas prontos: veja ``backdrop.THEMES``. Eles são renderizados uma vez em ``~/.auto-edit/backdrops/``.
"""
from __future__ import annotations

import json
from pathlib import Path

from auto_edit import backdrop, config

BACKDROP_SIZE = (1920, 1080)


def config_path() -> Path:
    return config.home_dir() / "presenter.json"


def load_config() -> dict:
    p = config_path()
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_config(cfg: dict) -> Path:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def pick_backdrop(cfg: dict, context: str) -> str | None:
    """Fundo (nome de tema ou caminho de imagem) para um contexto: vale o primeiro assunto de ``topics`` encontrado."""
    ctx = (context or "").lower()
    for topic, entry in (cfg.get("topics") or {}).items():
        if topic.lower() in ctx and entry.get("backdrop"):
            return entry["backdrop"]
    return cfg.get("default_backdrop")


def backdrop_file(spec: str) -> Path | None:
    """Nome de tema -> PNG renderizado (em cache); senão, um caminho de imagem que exista; senão None."""
    if spec in backdrop.THEMES:
        out = config.home_dir() / "backdrops" / f"{spec}.png"
        return out if out.is_file() else backdrop.make_backdrop(spec, BACKDROP_SIZE, out)
    p = Path(spec).expanduser()
    return p if p.is_file() else None


def resolve_backdrop(context: str) -> Path | None:
    spec = pick_backdrop(load_config(), context)
    return backdrop_file(spec) if spec else None


def thumbnail_backdrop(context: str) -> Path | None:
    """Fundo da thumbnail do long, ou None quando a opção de thumbnail está desligada."""
    return resolve_backdrop(context) if load_config().get("thumbnail") else None
