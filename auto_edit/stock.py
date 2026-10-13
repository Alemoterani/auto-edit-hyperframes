"""
Fotos do assunto para a capa, do Pexels (grátis, uso livre sem crédito obrigatório).

Chave grátis em pexels.com/api, na variável ``PEXELS_API_KEY``. Sem custo por uso; o limite do plano grátis
(200 buscas por hora) sobra para capas.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.pexels.com/v1/search"


def _ssl_from_windows() -> None:
    """HTTPS pelos certificados do sistema: nesta máquina o antivírus inspeciona o TLS e o bundle do Python recusa."""
    try:
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        pass


def _open(req: urllib.request.Request | str, timeout: float = 30):
    _ssl_from_windows()
    return urllib.request.urlopen(req, timeout=timeout)


def search(query: str, orientation: str = "landscape", n: int = 4) -> list[dict]:
    """Até ``n`` fotos para ``query`` (em inglês busca melhor): ``[{id, url, alt, photographer}]``.
    ``orientation``: landscape, portrait ou square."""
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        raise RuntimeError("Defina PEXELS_API_KEY (chave grátis em pexels.com/api) para buscar as fotos da capa")
    qs = urllib.parse.urlencode({"query": query, "orientation": orientation, "per_page": n})
    req = urllib.request.Request(f"{API}?{qs}", headers={"Authorization": key, "User-Agent": "auto-edit-video"})
    with _open(req) as resp:
        photos = json.load(resp).get("photos", [])
    return [{"id": p["id"], "url": p["src"]["large2x"], "alt": p.get("alt", ""),
             "photographer": p.get("photographer", "")} for p in photos[:n]]


def download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "auto-edit-video"})
    with _open(req, timeout=60) as resp:
        dest.write_bytes(resp.read())
    return dest
