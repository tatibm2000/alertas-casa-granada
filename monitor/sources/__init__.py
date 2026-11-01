from __future__ import annotations

from ..utils import Http
from .apis import Comprarcasa, GrupoTorres, Ventaria, WpHouzez
from .base import Source
from .browser_sites import Deymar, KwKinver
from .generic import Generic
from .inmovilla import Inmovilla
from .simple_html import Aphome, DonPiso, Inmo30, PisosCom, Remax, Tecnocasa

KINDS: dict[str, type[Source]] = {
    cls.kind: cls
    for cls in [Inmovilla, Aphome, Remax, PisosCom, Tecnocasa, DonPiso, Inmo30,
                WpHouzez, Ventaria, GrupoTorres, Comprarcasa, Deymar, KwKinver, Generic]
}


def build_sources(cfg_sources: list[dict], http: Http) -> list[Source]:
    out = []
    for s in cfg_sources:
        if not s.get("enabled", True):
            continue
        opts = {k: v for k, v in s.items() if k not in {"id", "name", "kind", "enabled"}}
        cls = KINDS[s["kind"]]
        out.append(cls(s["id"], s.get("name", s["id"]), http, **opts))
    return out