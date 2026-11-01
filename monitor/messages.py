from __future__ import annotations

import re

from .models import Listing
from .telegram import esc
from .utils import norm


def eur(n: int | None) -> str:
    return "precio a consultar" if n is None else f"{n:,.0f} €".replace(",", ".")


def _details(it: Listing) -> str:
    bits = [f"<b>{eur(it.price)}</b>"]
    if it.rooms is not None:
        bits.append(f"{it.rooms} hab")
    if it.m2:
        bits.append(f"{it.m2} m²")
    return " · ".join(bits)


def tipo(it: Listing) -> str:
    """Tipo de vivienda bonito: 'Piso', 'Casa adosada', 'Chalet'... ('Vivienda' si la web no lo da)."""
    t = (it.ptype or "").strip()
    if not t:
        return "Vivienda"
    return t[0].upper() + t[1:].lower()


def _place(it: Listing) -> str:
    muni = it.municipality or ""
    zona = (it.extra or {}).get("zona") or ""
    if zona and zona.lower() != muni.lower():
        muni = f"{muni} ({zona})" if muni else zona
    donde = f" en {esc(muni)}" if muni else ""
    return f"🏡 <b>{esc(tipo(it))}</b>{donde}\n"


def _title(it: Listing) -> str:
    """Título de la web, solo si aporta algo que no digan ya las líneas de tipo, precio y m²."""
    t = re.sub(r"\s+", " ", (it.title or "")).strip()
    if not t:
        return ""
    # Fuera trozos de ficha técnica: "Referencia X Habitaciones 3 Baños 1 Superficie 188 m2"
    if re.search(r"\b(habitaciones|baños|superficie)\s+\d", t, re.I) or len(t) > 140:
        return ""
    nt = norm(t)
    ya = norm(f"{tipo(it)} en {it.municipality or ''}")
    if nt in ya or nt in norm(it.municipality or "") or nt == norm(tipo(it)):
        return ""
    return f"<i>{esc(t)}</i>\n"


def new_listing(it: Listing, source_name: str, note: str = "") -> str:
    return (
        f"🏠 <b>NUEVO</b> · {esc(source_name)}\n"
        f"{_place(it)}{_details(it)}\n{_title(it)}"
        f"{note + chr(10) if note else ''}"
        f'<a href="{esc(it.url)}">Ver anuncio</a>'
    )


def price_drop(it: Listing, old: int, source_name: str) -> str:
    pct = (old - (it.price or old)) / old * 100 if old else 0
    return (
        f"📉 <b>BAJADA DE PRECIO</b> · {esc(source_name)}\n"
        f"{_place(it)}<s>{eur(old)}</s> → {_details(it)}  (−{pct:.0f} %)\n"
        f"{_title(it)}"
        f'<a href="{esc(it.url)}">Ver anuncio</a>'
    )


def fallback(it: Listing, source_name: str, max_price: int, min_rooms: int) -> str:
    return (
        f"ℹ️ <b>{esc(source_name)}</b>: ahora mismo no tiene nada ≤ {eur(max_price)} con {min_rooms}+ hab.\n"
        f"El más reciente con {min_rooms}+ habitaciones es:\n"
        f"{_place(it)}{_details(it)}\n{_title(it)}"
        f'<a href="{esc(it.url)}">Ver anuncio</a>'
    )


def duplicate(it: Listing, source_name: str, first_source: str, first_url: str | None) -> str:
    extra = f' — ya avisado desde <a href="{esc(first_url)}">{esc(first_source)}</a>' if first_url else f" — ya avisado desde {esc(first_source)}"
    return (
        f"🔁 El mismo inmueble ({eur(it.price)}, {it.rooms} hab, {esc(it.municipality)}) "
        f"también lo anuncia <b>{esc(source_name)}</b>{extra}: "
        f'<a href="{esc(it.url)}">ver aquí</a>'
    )