"""Webs hechas con el CRM Inmovilla (Inmofuturo, Invivus, JyM, InmoAire, Neo Patrimonial).

Listado de venta ordenado por "Más reciente":   {base}/venta/?orden=5
Ficha:                                          {base}/ficha/{tipo}/{municipio}/{zona}/{agencia}/{id}/es/
RSS (respaldo, 19 últimos):                     {base}/rss
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import Listing, id_sort_key
from ..utils import clean, m2_from_text, parse_int, parse_price, rooms_from_text
from .base import Source, unique

log = logging.getLogger(__name__)

FICHA_RE = re.compile(r"ficha/([^/]+)/([^/]+)/(?:([^/]+)/)?(\d+)/(\d+)/")


def _slug_to_text(s: str) -> str:
    return s.replace("-", " ").strip().title() if s else ""


class Inmovilla(Source):
    kind = "inmovilla"

    def list_url(self) -> str:
        # Plantillas antiguas (p. ej. 4Arcos) usan venta.php: se indica con list_path en config.yaml
        path = self.opts.get("list_path") or "venta/?orden=5"
        return f"{self.base_url}/{path.lstrip('/')}"

    def fetch(self) -> list[Listing]:
        url = self.list_url()
        self.complete = False  # solo leemos la primera página (los 12 más recientes)
        if self.opts.get("browser_sort"):
            # Plantilla antigua (venta.php): sale ordenada por precio y el orden "Más recientes"
            # solo se puede elegir en el desplegable, así que lo elegimos con el navegador.
            html = self._sorted_in_browser(url)
            if html:
                return self.parse_list(html, url)
        html = self.http.get_text(url)
        return self.parse_list(html, url)

    def _sorted_in_browser(self, url: str) -> str | None:
        try:
            from .browser_sites import browser_page
        except ImportError:
            return None
        with browser_page() as page:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(1500)
            chosen = page.evaluate(
                """() => {
                  const re = /m[aá]s\\s+recientes?|most\\s+recent|recientes/i;
                  for (const s of document.querySelectorAll('select')) {
                    for (const o of s.options) {
                      if (re.test(o.text)) {
                        s.value = o.value;
                        s.dispatchEvent(new Event('change', {bubbles: true}));
                        return o.text;
                      }
                    }
                  }
                  return null;
                }"""
            )
            if not chosen:
                try:
                    page.get_by_text(re.compile(r"m[aá]s\s+recientes?", re.I)).first.click(timeout=5000)
                    chosen = "clic"
                except Exception:  # noqa: BLE001
                    log.warning("%s: no encontré el orden 'Más recientes'; leo el listado tal cual", self.id)
                    return None
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(2500)
            return page.content()

    def parse_list(self, html: str, page_url: str) -> list[Listing]:
        soup = BeautifulSoup(html, "lxml")
        base_tag = soup.find("base", href=True)
        base = base_tag["href"] if base_tag else self.base_url + "/"
        if not base.endswith("/"):
            base += "/"

        use_class = bool(soup.select_one("a.irAfichaPropiedad[href]"))

        def ficha_links(tag):
            if use_class:
                return tag.select("a.irAfichaPropiedad[href]")
            return [x for x in tag.find_all("a", href=True) if FICHA_RE.search(x["href"])]

        def ids_in(tag) -> set[str]:
            out = set()
            for x in ficha_links(tag):
                m = FICHA_RE.search(x["href"])
                if m:
                    out.add(m.group(5))
            return out

        out: list[Listing] = []
        for a in ficha_links(soup):
            full = urljoin(base, a["href"])
            m = FICHA_RE.search(full)
            if not m:
                continue
            ptype, muni, zona, _agency, pid = m.groups()
            # Contenedor de la tarjeta: subimos hasta tener el precio, sin mezclar otros anuncios.
            # (Inmovilla tiene varias plantillas: "paginacion-ficha", "paginacion-ficha-contenedorprincipal-4"...)
            box = a
            while box.parent is not None and "€" not in box.get_text():
                box = box.parent
            while box.parent is not None and box.parent.name != "body" and ids_in(box.parent) == {pid}:
                box = box.parent
            if len(ids_in(box)) > 1:
                box = None  # no hemos aislado la tarjeta: se completará desde la ficha
            text = clean(box.get_text(" ")) if box else ""

            pm = re.search(r"(?:Venta|Vender)\s+([\d.]+)\s*€", text) or re.search(r"(\d{1,3}(?:\.\d{3})+)\s*€", text)
            price = parse_price(pm.group(1)) if pm else None
            rooms = rooms_from_text(text)
            if rooms is None and pm:
                # Plantilla compacta: "154.900 € AIRE-P42 2 2 89 m2" (ref, habitaciones, baños, m2)
                rm = re.match(r"\s*\S+\s+(\d{1,2})\s+\d{1,2}\s+[\d.,]+\s*m2", text[pm.end():])
                rooms = int(rm.group(1)) if rm else None
            # Título: el encabezado de la tarjeta, no todo su texto (que repite ref, hab, m²...)
            title = ""
            if box is not None:
                t_el = box.select_one("h1, h2, h3, h4, [class*='titulo'], [class*='title']")
                if t_el is not None:
                    title = clean(t_el.get_text(" "))
            photo_el = box.select_one("[cargafoto]") if box else None
            img = box.select_one("img[src*='apinmo'], img[src*='inmovilla']") if box else None
            is_rent = bool(re.search(r"\bAlquiler\s+[\d.]+\s*€", text)) and not re.search(r"\bVenta\b", text)
            out.append(
                self.L(
                    id=pid,
                    url=full,
                    title=title[:160],
                    municipality=_slug_to_text(muni),
                    ptype=_slug_to_text(ptype),
                    price=price,
                    rooms=rooms,
                    m2=m2_from_text(text),
                    photo=(photo_el.get("cargafoto") if photo_el else None) or (img.get("src") if img else None),
                    sort_key=id_sort_key(pid),
                    province_ok=None if self.geo_check else True,
                    is_sale=not is_rent,
                    needs_enrich=rooms is None or price is None,
                )
            )
        return unique(out)

    def enrich(self, it: Listing) -> None:
        html = self.http.get_text(it.url)
        soup = BeautifulSoup(html, "lxml")
        carac = {}
        for span in soup.select("span.caracteristica"):
            val = span.find_next_sibling(class_="valor")
            if val:
                carac[clean(span.get_text()).lower()] = clean(val.get_text())
        if "habitaciones" in carac:
            it.rooms = parse_int(carac["habitaciones"])
        elif it.rooms is None:
            it.rooms = rooms_from_text(soup.get_text(" "))
        precio = soup.select_one(".fichapropiedad-bloqueprecio")
        if precio and it.price is None:
            it.price = parse_price(precio.get_text(" ").replace("Proponer un precio", ""))
        if "zona / ciudad" in carac:
            it.municipality = carac["zona / ciudad"].split("/")[-1].strip() or it.municipality
        for k in ("superficie construida", "superficie útil", "superficie"):
            if k in carac and not it.m2:
                it.m2 = parse_int(carac[k].replace(".", ""))
        if "tipo de propiedad" in carac:
            it.ptype = carac["tipo de propiedad"]
        if "tipo operación" in carac:
            it.is_sale = "vend" in carac["tipo operación"].lower()
        og = soup.find("meta", property="og:image")
        if og and not it.photo:
            it.photo = og.get("content")
        og_t = soup.find("meta", property="og:title")
        if og_t and og_t.get("content"):
            it.title = og_t["content"]
        it.needs_enrich = False