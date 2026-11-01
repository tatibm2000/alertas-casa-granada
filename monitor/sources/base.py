from __future__ import annotations

import logging
from typing import Iterable

from ..models import Listing
from ..utils import Http

log = logging.getLogger(__name__)


class Source:
    """Clase base de un conector.

    - `fetch()` devuelve los anuncios en venta que publica la web (ya normalizados).
    - `enrich(listing)` completa datos que solo están en la ficha (habitaciones, precio...).
    """

    kind = "base"
    needs_browser = False

    def __init__(self, sid: str, name: str, http: Http, **opts):
        self.id = sid
        self.name = name
        self.http = http
        self.opts = opts
        self.base_url = opts.get("base_url", "").rstrip("/")
        # True si la fuente puede traer inmuebles fuera de la provincia de Granada
        self.geo_check = bool(opts.get("geo_check", False))
        # True si el último fetch() trajo el catálogo completo (permite marcar retirados)
        self.complete = True

    def fetch(self) -> list[Listing]:
        raise NotImplementedError

    def enrich(self, listing: Listing) -> None:  # pragma: no cover - por defecto no hace nada
        return None

    def L(self, **kw) -> Listing:
        return Listing(source=self.id, **kw)

    def __repr__(self) -> str:
        return f"<{self.kind}:{self.id}>"


def unique(items: Iterable[Listing]) -> list[Listing]:
    seen, out = set(), []
    for it in items:
        if it.id and it.id not in seen:
            seen.add(it.id)
            out.append(it)
    return out
