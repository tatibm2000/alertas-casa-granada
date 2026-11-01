"""Conectores con API JSON: Plancasa (WordPress/Houzez), Ventaria (WP REST propio),
Grupo Torres (API del buscador) y Comprarcasa Portal Home (api.comprarcasa.com)."""
from __future__ import annotations

import html as htmllib
import logging

from ..models import Listing, id_sort_key
from ..utils import parse_int, parse_price
from .base import Source, unique

log = logging.getLogger(__name__)


def _first(v):
    if isinstance(v, list):
        return v[0] if v else None
    return v


# ------------------------------------------------------------------ Plancasa (Houzez)
class WpHouzez(Source):
    """/wp-json/wp/v2/properties?orderby=date&order=desc&_embed=wp:term,wp:featuredmedia"""

    kind = "wp_houzez"

    def fetch(self) -> list[Listing]:
        out: list[Listing] = []
        pages = int(self.opts.get("pages", 3))
        for page in range(1, pages + 1):
            url = (
                f"{self.base_url}/wp-json/wp/v2/properties?per_page=50&page={page}"
                f"&orderby=date&order=desc&_embed=wp:term,wp:featuredmedia"
            )
            try:
                data = self.http.get_json(url)
            except Exception:  # noqa: BLE001 - WP devuelve 400 al pasarse de página
                if page == 1:
                    raise
                break
            if not data:
                break
            out.extend(self.parse(data))
            if len(data) < 50:
                break
        return unique(out)

    def parse(self, data: list[dict]) -> list[Listing]:
        out = []
        for p in data:
            terms = {}
            for group in (p.get("_embedded") or {}).get("wp:term", []) or []:
                for t in group or []:
                    terms.setdefault(t.get("taxonomy"), []).append(htmllib.unescape(t.get("name", "")))
            status = " ".join(terms.get("property_status", [])).lower()
            meta = p.get("property_meta") or {}
            media = (p.get("_embedded") or {}).get("wp:featuredmedia") or []
            photo = media[0].get("source_url") if media and isinstance(media[0], dict) else None
            state = " ".join(terms.get("property_state", []))
            out.append(
                self.L(
                    id=str(p["id"]),
                    url=p.get("link", ""),
                    title=htmllib.unescape((p.get("title") or {}).get("rendered", "")),
                    municipality=_first(terms.get("property_city")) or _first(terms.get("property_area")) or "",
                    ptype=_first(terms.get("property_type")) or "",
                    price=parse_price(_first(meta.get("fave_property_price"))),
                    rooms=parse_int(_first(meta.get("fave_property_bedrooms"))),
                    m2=parse_int(_first(meta.get("fave_property_size"))),
                    photo=photo,
                    sort_key=p.get("date", ""),
                    province_ok=(state.lower() == "granada") if state else None,
                    is_sale=("venta" in status) if status else True,
                )
            )
        return out


# ------------------------------------------------------------------ Ventaria
class Ventaria(Source):
    """/wp-json/ventaria/v1/properties?page=N  (9 por página; se pide hasta que viene vacía)"""

    kind = "ventaria"

    def fetch(self) -> list[Listing]:
        out: list[Listing] = []
        for page in range(1, int(self.opts.get("max_pages", 15)) + 1):
            try:
                data = self.http.get_json(f"{self.base_url}/wp-json/ventaria/v1/properties?page={page}")
            except Exception:  # noqa: BLE001 - pasado el final WordPress devuelve error
                if page == 1:
                    raise
                break
            items = self.parse(data)
            if not items or {i.id for i in items} <= {i.id for i in out}:
                break
            out.extend(items)
        return unique(out)

    def parse(self, data) -> list[Listing]:
        items = data if isinstance(data, list) else data.get("properties", [])
        out = []
        min_sale = int(self.opts.get("min_sale_price", 15000))
        for p in items:
            price = parse_price(p.get("price"))
            ptypes = p.get("property_type") or []
            out.append(
                self.L(
                    id=str(p["id"]),
                    url=p.get("permalink", ""),
                    title=p.get("title", ""),
                    municipality=_first(p.get("zones")) or "",
                    ptype=p.get("property_type_extended") or _first(ptypes) or "",
                    price=price,
                    rooms=parse_int(p.get("rooms")),
                    m2=parse_int(p.get("building-area") or p.get("surface")),
                    photo=(p.get("thumbnail") or {}).get("url"),
                    sort_key=id_sort_key(p["id"]),
                    province_ok=True,
                    # El endpoint mezcla venta y alquiler y no trae operación: un precio
                    # muy bajo en una vivienda es casi seguro un alquiler.
                    is_sale=price is None or price >= min_sale,
                )
            )
        return out


# ------------------------------------------------------------------ Grupo Torres
class GrupoTorres(Source):
    """https://grupotorres.com/buscador/api/propiedades (catálogo entero, se filtra aquí)"""

    kind = "grupotorres"

    def fetch(self) -> list[Listing]:
        data = self.http.get_json(f"{self.base_url}/buscador/api/propiedades")
        cities: dict = {}
        try:
            # id de ciudad -> nombre del municipio (el anuncio solo trae el id y el barrio/zona)
            for c in self.http.get_json(f"{self.base_url}/buscador/api/ciudades"):
                cities[c.get("id")] = c.get("nombre") or ""
        except Exception as e:  # noqa: BLE001
            log.info("grupotorres: sin lista de municipios (%s), se mostrará la zona", e)
        return unique(self.parse(data, cities))

    def parse(self, data, cities: dict | None = None) -> list[Listing]:
        cities = cities or {}
        items = data if isinstance(data, list) else data.get("data", [])
        out = []
        for p in items:
            prov = ((p.get("provincia") or {}).get("nombre") or "").lower()
            tipo = p.get("Tipo_Oferta") or {}
            accion = (p.get("accion") or "").lower()
            fotos = p.get("fotos") or []
            pid = p.get("idInmovilla") or p.get("id")
            zona = (p.get("Zona") or {}).get("nombre") or ""
            titulo = p.get("titulo1") or ""
            is_viv_cat = tipo.get("categoriaId") == 1
            out.append(
                self.L(
                    id=str(pid),
                    url=f"{self.base_url}/buscador/propiedades/{pid}",
                    title=titulo,
                    municipality=cities.get(p.get("ciudadId")) or zona,
                    ptype=tipo.get("nombre", "") if is_viv_cat else (tipo.get("nombre") or "otro") + " (no vivienda)",
                    price=parse_price(p.get("precioinmo")),
                    rooms=parse_int(p.get("habitaciones")) or parse_int(p.get("habdobles")),
                    m2=parse_int(p.get("m_cons")),
                    photo=fotos[0].get("url") if fotos and isinstance(fotos[0], dict) else None,
                    sort_key=p.get("fecha") or "",
                    province_ok=prov == "granada",
                    is_sale="vend" in accion,  # Vender, Vender o Alquilar, Traspasar y Vender...
                    extra={"ref": p.get("ref"), "zona": zona},
                )
            )
        return out


# ------------------------------------------------------------------ Comprarcasa Portal Home
class Comprarcasa(Source):
    """api.comprarcasa.com/web/ListProperties/{web_id}?page=N&numProperties=50&orderBy=3"""

    kind = "comprarcasa"
    API = "https://api.comprarcasa.com"

    def fetch(self) -> list[Listing]:
        web_id = self.opts["web_id"]
        towns = {}
        try:
            cfg = self.http.get_json(f"{self.API}/web/GetInitConfigProperties?language=1", headers=self._hdr())
            towns = {t["id"]: (t.get("provincia") or "").upper() for t in cfg.get("towns", [])}
        except Exception as e:  # noqa: BLE001
            # No es grave: sin la lista se comprueba la provincia por el nombre del municipio
            log.info("comprarcasa: sin lista de municipios (%s), filtro por nombre", e)
        out: list[Listing] = []
        page, per = 1, 50
        while page <= int(self.opts.get("max_pages", 10)):
            data = self.http.get_json(
                f"{self.API}/web/ListProperties/{web_id}?page={page}&numProperties={per}&reference=&orderBy=3",
                headers=self._hdr(),
            )
            items = data.get("items") or []
            out.extend(self.parse(items, towns))
            if len(items) < per or len(out) >= int(data.get("totalItems") or 0):
                break
            page += 1
        return unique(out)

    def _hdr(self) -> dict:
        site = self.opts.get("site_url", "https://portalhome.comprarcasa.com").rstrip("/")
        return {"Origin": site, "Referer": site + "/"}

    def parse(self, items: list[dict], towns: dict | None = None) -> list[Listing]:
        towns = towns or {}
        site = self.opts.get("site_url", "https://portalhome.comprarcasa.com").rstrip("/")
        out = []
        for p in items:
            prov = towns.get(p.get("locationId"))
            out.append(
                self.L(
                    id=str(p["id"]),
                    url=f"{site}/inmueble/{p['id']}",
                    title=p.get("title") or f"{p.get('type', '')} en {p.get('location', '')}",
                    municipality=p.get("location") or "",
                    ptype=p.get("type") or "",
                    price=parse_price(p.get("price")),
                    rooms=parse_int(p.get("rooms")),
                    m2=parse_int(p.get("area")),
                    photo=p.get("mainPhoto"),
                    sort_key=id_sort_key(p["id"]),
                    province_ok=(prov == "GRANADA") if prov else None,
                    is_sale=bool(p.get("isSell")),
                    extra={"ref": p.get("reference"), "zone": p.get("zone")},
                )
            )
        return out