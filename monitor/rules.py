"""Reglas de negocio: qué es una vivienda válida y qué anuncio dispara un aviso."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Listing
from .municipios import variantes_zona
from .utils import in_granada, is_vivienda, norm, set_excluded_types


@dataclass
class Criteria:
    max_price: int = 220_000
    min_rooms: int = 3
    min_price: int = 100_000         # precio mínimo (por debajo: ruinas, alquileres, errores...)
    fallback: bool = True            # regla de rescate por portal
    price_drop_min_pct: float = 1.0  # % mínimo de bajada para avisar
    exclude_types: tuple = ()        # tipos extra a excluir además de los de utils.NO_VIVIENDA
    zona: tuple = ()                 # lista cerrada de municipios (vacía = toda la provincia)

    @classmethod
    def from_cfg(cls, d: dict) -> "Criteria":
        c = cls(**{k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__})
        c.zona = tuple(c.zona or ())
        set_excluded_types(list(c.exclude_types or []))
        return c


def vivienda(it: Listing) -> bool:
    v = is_vivienda(it.ptype, it.title)
    if v is None:
        # Sin tipo: si tiene habitaciones lo tratamos como vivienda
        return bool(it.rooms and it.rooms > 0)
    return v


_ZONA_CACHE: dict = {}


def _zona_patterns(zona: tuple):
    key = tuple(zona)
    if key not in _ZONA_CACHE:
        pats = []
        for v in variantes_zona(list(zona)):
            n = norm(v)
            if n:
                pats.append(re.compile(r"(?:^| )" + re.escape(n) + r"(?: |$)"))
        _ZONA_CACHE[key] = pats
    return _ZONA_CACHE[key]


def in_zona(it: Listing, zona: tuple) -> bool:
    """¿Está el anuncio en uno de los municipios elegidos?

    Se mira el campo municipio (lo que publica la web). Solo si la web no lo da se miran
    el título y la URL, para no confundir "piso en Granada cerca de Armilla" con Armilla."""
    pats = _zona_patterns(zona)
    url_txt = it.url.replace("-", " ").replace("_", " ").replace("/", " ")
    texts = [it.municipality, it.extra.get("location") if it.extra else None]
    if not any(t for t in texts):
        texts = [it.title, url_txt]
    blob = " " + " ".join(norm(t) for t in texts if t) + " "
    if any(p.search(blob) for p in pats):
        return True
    # Algunas webs ponen "Granada" (la provincia) como ciudad de todo: en ese caso
    # miramos también la dirección del anuncio (".../piso-en-venta-calle-mirasol-armilla/").
    if norm(it.municipality or "") == "granada":
        u = " " + norm(url_txt) + " "
        return any(p.search(u) for p in pats)
    return False


def geo_ok(it: Listing, c: "Criteria | None" = None) -> bool:
    if c is not None and c.zona:
        return in_zona(it, c.zona)
    if it.province_ok is not None:
        return it.province_ok
    return in_granada(it.municipality, it.title, it.extra.get("location"), it.url)


def base_ok(it: Listing, c: Criteria) -> bool:
    """Vivienda en venta en la provincia con el mínimo de habitaciones (sin mirar precio)."""
    return (
        it.is_sale
        and geo_ok(it, c)
        and vivienda(it)
        and it.rooms is not None
        and it.rooms >= c.min_rooms
    )


def matches(it: Listing, c: Criteria) -> bool:
    return base_ok(it, c) and it.price is not None and c.min_price <= it.price <= c.max_price


def fallback_ok(it: Listing, c: Criteria) -> bool:
    """Candidato para la regla de rescate: vivienda 3+ hab con precio ≥ mínimo (sin tope)."""
    return base_ok(it, c) and it.price is not None and it.price >= c.min_price


def maybe_relevant(it: Listing, c: Criteria) -> bool:
    """¿Merece la pena abrir la ficha para completar datos?"""
    if not it.is_sale or is_vivienda(it.ptype, it.title) is False:
        return False
    if it.province_ok is False and not c.zona:
        return False
    if c.zona and (it.municipality or (it.extra or {}).get("location")) and not in_zona(it, c.zona):
        return False  # municipio conocido y fuera de la zona: no gastamos una visita a la ficha
    if it.rooms is not None and it.rooms < c.min_rooms:
        return False
    return True


def fingerprint(it: Listing) -> str:
    """Huella para detectar el mismo inmueble publicado por varias agencias."""
    if not (it.price and it.rooms and it.municipality):
        return ""
    muni = norm(it.municipality)
    return f"{muni}|{it.rooms}|{round(it.price / 1000)}"