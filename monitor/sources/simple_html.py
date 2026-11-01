"""Conectores HTML sencillos (sin API): Inmo Arrayán, Remax Cima, InmoZafiro (pisos.com),
Tecnocasa, DonPiso e Inmobiliaria 3.0."""
from __future__ import annotations

import json
import logging
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from requests.utils import requote_uri

from ..models import Listing, id_sort_key
from ..utils import clean, m2_from_text, parse_int, parse_price, rooms_from_text
from .base import Source, img_url, unique

log = logging.getLogger(__name__)


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


# ------------------------------------------------------------------ Inmo Arrayán (APHome)
class Aphome(Source):
    """https://www.inmoarrayan.com/buscarInmuebles?... (orden por defecto: fecha desc)"""

    kind = "aphome"

    def list_url(self, page: int = 1) -> str:
        url = (
            f"{self.base_url}/buscarInmuebles?idTransaccion=1&idTipo=0&precioaAlquiler=0"
            f"&precio=0&idProvincia=18&idPoblacion=0&dormitoriosMin={self.opts.get('min_rooms', 3)}"
        )
        return url + (f"&pagina={page}" if page > 1 else "")

    def fetch(self) -> list[Listing]:
        url = self.list_url()
        return self.parse(self.http.get_text(url), url)

    def parse(self, html: str, page_url: str) -> list[Listing]:
        out = []
        for box in _soup(html).select("div.listarInmuebles_texto"):
            a = box.select_one(".listado_inmuebles_titulo a[href]") or box.select_one("a[href*='/propiedad/']")
            if not a:
                continue
            url = urljoin(page_url, a["href"])
            pid = url.rstrip("/").split("/")[-1]
            pobl = clean(box.select_one(".listado_inmuebles_poblacion").get_text()) if box.select_one(".listado_inmuebles_poblacion") else ""
            muni, _, ptype = pobl.partition(" - ")
            transac = clean(box.select_one(".listado_inmuebles_transaccion").get_text()) if box.select_one(".listado_inmuebles_transaccion") else "Venta"
            card = box.parent
            img = card.select_one("img") if card else None
            out.append(
                self.L(
                    id=pid,
                    url=url,
                    title=clean(a.get_text()),
                    municipality=muni,
                    ptype=ptype,
                    price=parse_price(box.select_one(".listado_inmuebles_precio").get_text()) if box.select_one(".listado_inmuebles_precio") else None,
                    rooms=parse_int(box.select_one(".listado_inmuebles_habitaciones").get_text()) if box.select_one(".listado_inmuebles_habitaciones") else None,
                    m2=m2_from_text(box.get_text(" ")),
                    photo=img_url(img, page_url),
                    sort_key=id_sort_key(pid),
                    province_ok=True,
                    is_sale="venta" in transac.lower(),
                )
            )
        return unique(out)


# ------------------------------------------------------------------ Remax Cima
class Remax(Source):
    """https://www.remaxcima.es/buscador-de-inmuebles/venta/todos/granada/"""

    kind = "remax"

    def fetch(self) -> list[Listing]:
        url = self.opts.get("list_url") or f"{self.base_url}/buscador-de-inmuebles/venta/todos/granada/"
        return self.parse(self.http.get_text(url), url)

    def parse(self, html: str, page_url: str) -> list[Listing]:
        out = []
        prefix = self.opts.get("ref_prefix")  # p.ej. "CIMA" para quedarnos solo con los propios
        for card in _soup(html).select("div.layer-wrapper"):
            a = card.select_one(".inmueble-detalle-nombre a[href]") or card.select_one("a[href*='/todos/']")
            if not a:
                continue
            # Los enlaces vienen como "../buscador-de-inmuebles/..." relativos a la raíz del sitio
            url = urljoin((self.base_url or page_url) + "/", re.sub(r"^(\.\./)+", "", a["href"]))
            ref = url.rstrip("/").split("/")[-1]
            if prefix and not ref.upper().startswith(prefix.upper()):
                continue
            name = clean(a.get_text())  # "Casa en venta, Villanueva Mesía, Granada"
            parts = [p.strip() for p in name.split(",")]
            ptype = re.sub(r"\s+en venta.*$", "", parts[0], flags=re.I) if parts else ""
            muni = parts[1] if len(parts) > 1 else ""
            path = urlparse(url).path.split("/")
            prov_ok = "granada" in path
            text = clean(card.get_text(" "))
            img = card.select_one("img[src]")
            price_el = card.select_one(".inmueble-detalle-precio")
            out.append(
                self.L(
                    id=ref,
                    url=url,
                    title=name,
                    municipality=muni,
                    ptype=ptype,
                    price=parse_price(price_el.get_text()) if price_el else None,
                    rooms=rooms_from_text(text),
                    m2=m2_from_text(text),
                    photo=img_url(img, page_url),
                    sort_key=id_sort_key(ref),
                    province_ok=prov_ok,
                    is_sale="/venta/" in url,
                )
            )
        return unique(out)


# ------------------------------------------------------------------ InmoZafiro (microsite de pisos.com)
class PisosCom(Source):
    """https://www.inmozafiro.com/buscador/en_venta/?IdMAEProvincia=P00000000000018&IdTipoOperacion=4&HabitacionesMinimas=3"""

    kind = "pisoscom"

    def fetch(self) -> list[Listing]:
        url = (
            f"{self.base_url}/buscador/en_venta/?IdMAEProvincia={self.opts.get('province_code', 'P00000000000018')}"
            f"&IdTipoOperacion=4"
        )
        return self.parse(self.http.get_text(url), url)

    def parse(self, html: str, page_url: str) -> list[Listing]:
        out = []
        for card in _soup(html).select("div.media"):
            if card.find_parent("div", class_="media"):
                continue
            a = card.select_one("a[href*='/detalle/']")
            if not a:
                continue
            url = urljoin(page_url, a["href"])
            seg = urlparse(url).path.strip("/").split("/")  # detalle/en_venta/piso/granada/armilla/.../ID
            ptype = seg[2].replace("_", " ") if len(seg) > 2 else ""
            muni = seg[4].replace("_", " ").title() if len(seg) > 4 else ""
            pid = seg[-1]
            body = card.select_one(".media-body") or card
            text = clean(body.get_text(" "))
            price_el = body.select_one(".precio")
            img = card.select_one("[style*='background-image']")
            photo = None
            if img:
                m = re.search(r"url\('?([^')]+)", img.get("style", ""))
                photo = m.group(1) if m else None
            title_el = body.select_one("h2, h3, .titulo, a")
            rooms = rooms_from_text(text)
            out.append(
                self.L(
                    id=pid,
                    url=url,
                    title=clean(title_el.get_text()) if title_el else text[:120],
                    municipality=muni,
                    ptype=ptype,
                    price=parse_price(price_el.get_text()) if price_el else parse_price(text),
                    rooms=rooms,
                    m2=m2_from_text(text),
                    photo=photo,
                    sort_key="",  # sin fecha: se usa el orden de la página
                    province_ok=True,
                    is_sale="en_venta" in url,
                    needs_enrich=rooms is None,
                )
            )
        # La página no da fecha: conservamos el orden recibido como "recencia" aproximada
        n = len(out)
        for i, it in enumerate(out):
            it.sort_key = f"pos{n - i:06d}"
        return unique(out)

    def enrich(self, it: Listing) -> None:
        soup = _soup(self.http.get_text(it.url))
        text = clean(soup.get_text(" "))
        it.rooms = rooms_from_text(text)
        if it.m2 is None:
            it.m2 = m2_from_text(text)
        og = soup.find("meta", property="og:image")
        if og and not it.photo:
            it.photo = og.get("content")
        it.needs_enrich = False


# ------------------------------------------------------------------ Tecnocasa
class Tecnocasa(Source):
    """https://www.tecnocasa.es/venta/inmuebles/andalucia/granada.html/pag-N

    No hay orden por fecha en la URL, pero los ids son incrementales. Cada ciclo se leen
    `quick_pages` páginas y cada `full_every` ciclos se recorre todo el listado.
    """

    kind = "tecnocasa"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._cycle = 0

    def page_url(self, n: int) -> str:
        base = self.opts.get("list_url") or "https://www.tecnocasa.es/venta/inmuebles/andalucia/granada.html"
        if n == 1:
            return base
        # con filtros: .../granada.html/pag-2?min_price=...&sort=...
        path, _, query = base.partition("?")
        return f"{path}/pag-{n}" + (f"?{query}" if query else "")

    def fetch(self) -> list[Listing]:
        self._cycle += 1
        c = getattr(self, "cycle_hint", None) or self._cycle  # ciclo global si lo da el runner
        full = c == 1 or c % int(self.opts.get("full_every", 8)) == 0
        max_pages = int(self.opts.get("max_pages", 60)) if full else int(self.opts.get("quick_pages", 3))
        self.complete = full
        out: list[Listing] = []
        for n in range(1, max_pages + 1):
            url = self.page_url(n)
            items = self.parse(self.http.get_text(url), url)
            if not items:
                break
            new_ids = {i.id for i in items} - {i.id for i in out}
            if not new_ids:  # página repetida = fin del listado
                break
            out.extend(items)
        return unique(out)

    def parse(self, html: str, page_url: str) -> list[Listing]:
        soup = _soup(html)
        # Los anuncios vienen como JSON en el atributo :estates del componente Vue
        holder = soup.find(attrs={":estates": True})
        if holder is not None:
            try:
                data = json.loads(holder[":estates"])
                return self.parse_json(data)
            except ValueError as e:
                log.warning("tecnocasa: JSON :estates ilegible (%s), pruebo con las tarjetas", e)
        out = []
        for card in soup.select("div.estate-card"):
            a = card.select_one("a[href]")
            if not a:
                continue
            url = urljoin(page_url, a["href"])
            m = re.search(r"/(\d+)\.html", url)
            if not m:
                continue
            pid = m.group(1)
            sub = card.select_one(".estate-card-subtitle")
            title = card.select_one(".estate-card-title")
            rooms_el = card.select_one(".estate-card-rooms")
            surf = card.select_one(".estate-card-surface")
            price = card.select_one(".estate-card-current-price")
            img = card.select_one("img[src]")
            ptype = re.sub(r"\s+en venta.*$", "", clean(title.get_text()) if title else "", flags=re.I)
            out.append(
                self.L(
                    id=pid,
                    url=url,
                    title=f"{clean(title.get_text()) if title else ''} · {clean(sub.get_text()) if sub else ''}",
                    municipality=clean(sub.get_text()).split(",")[0] if sub else "",
                    ptype=ptype,
                    price=parse_price(price.get_text()) if price else None,
                    rooms=parse_int(rooms_el.get_text()) if rooms_el else None,
                    m2=parse_int(surf.get_text()) if surf else None,
                    photo=img_url(img, page_url),
                    sort_key=id_sort_key(pid),
                    province_ok=True,
                    is_sale="/venta/" in url,
                )
            )
        return out

    def parse_json(self, data: list[dict]) -> list[Listing]:
        out = []
        for e in data:
            if not isinstance(e, dict) or e.get("ad_type", "estate") != "estate" or not e.get("id"):
                continue
            pid = str(e["id"])
            url = e.get("detail_url") or ""
            title = clean(e.get("title") or "")
            sub = clean(e.get("subtitle") or "")
            imgs = e.get("images") or []
            photo = None
            if imgs and isinstance(imgs[0], dict):
                u = imgs[0].get("url") or {}
                photo = u.get("card") or u.get("gallery_media") if isinstance(u, dict) else u
            out.append(
                self.L(
                    id=pid,
                    url=url,
                    title=f"{title} · {sub}".strip(" ·"),
                    municipality=sub.split(",")[0].strip(),
                    ptype=re.sub(r"\s+en venta.*$", "", title, flags=re.I),
                    price=parse_price(e.get("price")),
                    rooms=parse_int(e.get("rooms") or e.get("rooms_short")),
                    m2=parse_int(re.sub(r"<[^>]+>", "", e.get("surface") or "")),
                    photo=photo,
                    sort_key=id_sort_key(pid),
                    province_ok=True,
                    is_sale="/venta/" in url,
                    needs_enrich=not (e.get("rooms") or e.get("rooms_short")),
                )
            )
        return out


    def enrich(self, it: Listing) -> None:
        import html as htmllib

        raw = self.http.get_text(it.url)
        soup = _soup(raw)
        text = clean(soup.get_text(" "))
        rooms = rooms_from_text(text)
        if rooms is None:
            # la ficha también lleva los datos en JSON dentro de atributos de Vue
            un = htmllib.unescape(raw)
            m = re.search(r'"id"\s*:\s*' + re.escape(it.id) + r'\b.{0,3000}?"rooms"\s*:\s*"(\d{1,2})', un, re.S)
            rooms = int(m.group(1)) if m else rooms_from_text(un[:200000])
        it.rooms = rooms
        if it.m2 is None:
            it.m2 = m2_from_text(text)
        it.needs_enrich = False


# ------------------------------------------------------------------ DonPiso
class DonPiso(Source):
    """https://www.donpiso.com/venta-casas-y-pisos/granada/listado (provincia entera)"""

    kind = "donpiso"

    def fetch(self) -> list[Listing]:
        url = self.opts.get("list_url") or "https://www.donpiso.com/venta-casas-y-pisos/granada/listado"
        return self.parse(self.http.get_text(url), url)

    def parse(self, html: str, page_url: str) -> list[Listing]:
        soup = _soup(html)
        out = []
        id_re = re.compile(r"/pisos-y-casas/(\d+)_")
        for a in soup.find_all("a", href=id_re):
            pid = id_re.search(a["href"]).group(1)
            # subimos hasta el contenedor que tiene precio y solo este anuncio
            box = a
            while box.parent is not None and "€" not in box.get_text():
                box = box.parent
            while (
                box.parent is not None
                and len({id_re.search(x["href"]).group(1) for x in box.parent.find_all("a", href=id_re)}) == 1
            ):
                box = box.parent
            text = clean(box.get_text(" "))
            m = re.search(r"([\wÁÉÍÓÚáéíóúñÑ ]+?) en venta en ([^/]+?)\s*/", text)
            tm = re.search(
                r"(Piso|Ático|Atico|Dúplex|Duplex|Estudio|Apartamento|Loft|Planta baja|Bajo|Casa(?: [A-ZÁÉÍÓÚ][a-záéíóú]+)?"
                r"|Chalet(?: [A-ZÁÉÍÓÚ][a-záéíóú]+)?|Adosado|Pareado|Cortijo|Finca|Local|Oficina|Garaje|Parking|Nave"
                r"|Solar|Terreno|Parcela|Trastero|Edificio)\s+en venta en",
                text,
            )
            img = box.select_one("img[src]")
            out.append(
                self.L(
                    id=pid,
                    url=requote_uri(urljoin(page_url, a["href"].split("&")[0].split("#")[0])),
                    title=text[:140],
                    municipality=clean(m.group(2)) if m else "",
                    ptype=tm.group(1) if tm else (m.group(1).split()[-1] if m else ""),
                    price=parse_price(re.search(r"([\d.]+)\s*€(?!/)", text).group(1)) if re.search(r"([\d.]+)\s*€(?!/)", text) else None,
                    rooms=rooms_from_text(text),
                    m2=m2_from_text(text),
                    photo=img_url(img, page_url),
                    sort_key=id_sort_key(pid),
                    province_ok=True,
                    is_sale=True,
                )
            )
        return unique(out)


# ------------------------------------------------------------------ Inmobiliaria 3.0
class Inmo30(Source):
    """https://www.inmobiliaria30.com/quiero-comprar/ (lista completa en una página)"""

    kind = "inmo30"

    def fetch(self) -> list[Listing]:
        url = f"{self.base_url}/quiero-comprar/"
        return self.parse(self.http.get_text(url), url)

    def parse(self, html: str, page_url: str) -> list[Listing]:
        out = []
        for a in _soup(html).find_all("a", href=re.compile(r"/inmuebles/.+-\d+/?$")):
            text = clean(a.get_text(" "))
            if "Precio venta" not in text:
                continue
            url = urljoin(page_url, a["href"])
            pid = re.search(r"-(\d+)/?$", a["href"]).group(1)
            pm = re.search(r"Precio venta:\s*([\d.]+)", text)
            # Iconos: fa-bed = habitaciones, fa-bath = baños, fa-warehouse = m2
            rooms = m2 = None
            for span in a.select("span.icon-caracteristicas"):
                icon = " ".join(span.i.get("class", [])) if span.i else ""
                val = clean(span.get_text(" "))
                if "fa-bed" in icon:
                    rooms = parse_int(val)
                elif "fa-warehouse" in icon or "fa-ruler" in icon or "m2" in val.replace(" ", ""):
                    m2 = parse_int(val.replace(".", ""))
            name = a.select_one("h3")
            ref = re.search(r"Ref:\s*(\w+)", text)
            img = a.select_one("img[src]")
            out.append(
                self.L(
                    id=pid,
                    url=url,
                    title=f"{ref.group(1) if ref else ''} {clean(name.get_text()) if name else ''}".strip(),
                    municipality=clean(name.get_text()).title() if name else "",
                    ptype="",
                    price=parse_price(pm.group(1)) if pm else None,
                    rooms=rooms,
                    m2=m2,
                    photo=img_url(img, page_url),
                    sort_key=id_sort_key(pid),
                    province_ok=True,
                    is_sale=True,
                )
            )
        return unique(out)
