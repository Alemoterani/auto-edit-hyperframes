"""
Fotos do assunto para a capa, do Openverse (api.openverse.org): sem chave, sem conta, sem custo.

Só fotos em domínio público (CC0 ou Public Domain Mark), que podem ser usadas sem dar crédito. O Pexels ficou de fora
porque parou de emitir chaves da API. O acesso anônimo tem limite de buscas por minuto, que sobra para capas.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.openverse.org/v1/images/"
ASPECT = {"landscape": "wide", "portrait": "tall", "square": "square"}
HEADERS = {"User-Agent": "auto-edit-video (capas; https://github.com/Alemoterani/auto-edit-hyperframes)"}


def _ssl_from_windows() -> None:
    """HTTPS pelos certificados do sistema: nesta máquina o antivírus inspeciona o TLS e o bundle do Python recusa."""
    try:
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        pass


def _open(req: urllib.request.Request, timeout: float = 30):
    _ssl_from_windows()
    return urllib.request.urlopen(req, timeout=timeout)


def _query(params: dict) -> list[dict]:
    req = urllib.request.Request(f"{API}?{urllib.parse.urlencode(params)}", headers=HEADERS)
    with _open(req) as resp:
        return json.load(resp).get("results", [])


def search(query: str, orientation: str = "landscape", n: int = 4) -> list[dict]:
    """Até ``n`` fotos grandes em domínio público para ``query`` (em inglês busca melhor):
    ``[{id, url, alt, photographer}]``. ``orientation``: landscape, portrait ou square (cai para qualquer formato
    quando não há foto naquele)."""
    params = {"q": query, "license": "cc0,pdm", "size": "large", "page_size": n}
    results = _query({**params, "aspect_ratio": ASPECT.get(orientation, "wide")}) or _query(params)
    return [{"id": r["id"], "url": r["url"], "alt": r.get("title", ""), "photographer": r.get("creator", "")}
            for r in results[:n]]


def download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with _open(urllib.request.Request(url, headers=HEADERS), timeout=60) as resp:
        dest.write_bytes(resp.read())
    return dest
