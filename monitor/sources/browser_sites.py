"""Webs que solo pintan los anuncios con JavaScript: Deymar (Inmovirtual) y KW Kinver (Next.js).

Se usa Playwright con Chromium sin interfaz. Si Playwright no está instalado, estas dos
fuentes se saltan con un aviso en el log y el resto del monitor funciona igual.
"""
from __future__ import annotations

import logging
import re
from contextlib import contextmanager

from bs4 import BeautifulSoup

from ..models import Listing, id_sort_key
from ..municipios import municipios
from ..utils import USER_AGENT, clean, m2_from_text, norm, parse_price, rooms_from_text
from .base import Source, unique

log = logging.getLogger(__name__)


@contextmanager
def browser_page(block_media: bool = True):
    from playwright.sync_api import sync_playwright  # import perezoso: dependencia opcional

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        try:
            ctx = browser.new_context(user_agent=USER_AGENT, locale="es-ES",
                                      viewport={"width": 1366, "height": 900})
            page = ctx.new_page()
            if block_media:
                # no descargamos imágenes ni fuentes: más rápido y menos carga para la web
                page.route(re.compile(r"\.(png|jpe?g|webp|gif|svg|woff2?|ttf|mp4)(\?|$)"),
                           lambda route: route.abort())
            yield page
        finally:
            browser.close()


# ------------------------------------------------------------------ Deymar (Inmovirtual)
class Deymar(Source):
    kind = "deymar"
    needs_browser = True

    def fetch(self) -> list[Listing]:
        url = self.opts.get("list_url") or (
            f"{self.base_url}/buscador-viviendas-piso-casas-inmobiliaria-pisos-casas-locales-gabias.html"
        )
        with browser_page() as page:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_selector(".room-item", timeout=45000)
            page.wait_for_timeout(1500)
            html = page.content()
        return self.parse(html, url)

    def parse(self, html: str, page_url: str) -> list[Listing]:
        out = []
        for card in BeautifulSoup(html, "lxml").select(".room-item"):
            link = None
            for a in card.select("a[href]"):
                if re.search(r"(venta-comprar|alquiler)/.+\.html|inmueble\.php\?ID=", a["href"]):
                    link = a
                    break
            if not link:
                continue
            from urllib.parse import urljoin

            url = urljoin(page_url, link["href"])
            text = clean(card.get_text(" "))
            ref = re.search(r"Ref\.?\s*(\d+)", text)
            pid = ref.group(1) if ref else re.sub(r"\D", "", url)[-12:]
            op = re.search(r"\b(Venta|Alquiler|Traspaso)\b", text)
            # "165.000 € Piso Venta Gabia Grande, Las Gabias 95m² 2 1 ..."
            tm = re.search(r"€\s*(?:REBAJADO\s*)?([A-ZÁÉÍÓÚÑa-záéíóúñ ]+?)\s+(Venta|Alquiler|Traspaso)\s+(.+?)\s+\d[\d.]*\s*m²", text)
            rm = re.findall(r"m²\s+(\d{1,2})\s+(\d{1,2})\s", text + " ")
            out.append(
                self.L(
                    id=pid,
                    url=url,
                    title=text[:140],
                    municipality=(tm.group(3).split(",")[-1].strip() if tm else ""),
                    ptype=(tm.group(1).strip() if tm else ""),
                    price=parse_price(re.search(r"([\d.]+)\s*€", text).group(1)) if re.search(r"([\d.]+)\s*€", text) else None,
                    rooms=int(rm[-1][0]) if rm else rooms_from_text(text),
                    m2=m2_from_text(text),
                    sort_key=id_sort_key(pid),
                    province_ok=True,
                    is_sale=(op.group(1) == "Venta") if op else True,
                )
            )
        return unique(out)


# ------------------------------------------------------------------ KW Kinver
KW_ID_RE = re.compile(r"inmovilla\.com(?:/|%2F)(\d+)(?:/|%2F)(\d{7,})(?:/|%2F)")


class KwKinver(Source):
    """Listado: https://www.kwkinver.com/es/listings/  (se pinta con JavaScript; las tarjetas no son enlaces)
    Ficha:   https://www.kwkinver.com/es/property/{id_inmovilla}/  (HTML servido desde el servidor)

    Con el navegador sacamos los ids de los anuncios (vienen en las URLs de las fotos de Inmovilla)
    y los datos (precio, habitaciones, municipio) se leen de la ficha solo para los anuncios nuevos.
    """

    kind = "kw"
    needs_browser = True

    def fetch(self) -> list[Listing]:
        url = self.opts.get("list_url") or f"{self.base_url}/es/listings/"
        agency = str(self.opts.get("agency", "2279"))
        api_bodies: list[str] = []

        def on_response(resp):
            # Guardamos lo que devuelve su API de anuncios (también trae los ids)
            if "webscms.com/api" in resp.url or "get_properties" in resp.url:
                try:
                    api_bodies.append(resp.text())
                except Exception:  # noqa: BLE001
                    pass

        with browser_page(block_media=False) as page:
            page.on("response", on_response)
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            try:
                page.wait_for_function("document.body.innerText.includes('€')", timeout=40000)
            except Exception:  # noqa: BLE001
                pass
            try:
                page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:  # noqa: BLE001
                pass
            for _ in range(int(self.opts.get("scrolls", 8))):
                page.mouse.wheel(0, 2500)
                page.wait_for_timeout(1000)
            html = page.content()
            ids: list[str] = []
            for blob in [html, *api_bodies]:
                for ag, pid in KW_ID_RE.findall(blob):
                    if ag == agency and pid not in ids:
                        ids.append(pid)
                # en el JSON de la API los ids van como "cod_ofer": 30642984 o "id": 30642984
                for pid in re.findall(r'"(?:cod_ofer|codOfer|id_inmovilla|idInmovilla)"\s*:\s*"?(\d{7,})', blob):
                    if pid not in ids:
                        ids.append(pid)
            if not ids:
                # Dejamos una copia para poder ver qué ha recibido el navegador
                from pathlib import Path

                dbg = Path("data")
                dbg.mkdir(exist_ok=True)
                (dbg / "debug_kw.html").write_text(html, encoding="utf-8")
                try:
                    page.screenshot(path=str(dbg / "debug_kw.png"), full_page=True)
                except Exception:  # noqa: BLE001
                    pass
                log.warning("kw: no encontré anuncios en el listado. He guardado data/debug_kw.html "
                            "y data/debug_kw.png para revisarlo (respuestas de API capturadas: %d)",
                            len(api_bodies))
        self.complete = False  # solo la primera página de resultados
        return [
            self.L(
                id=pid,
                url=f"{self.base_url}/es/property/{pid}/",
                sort_key=id_sort_key(pid),
                photo=f"https://fotos15.inmovilla.com/{agency}/{pid}/4-1.jpg",
                province_ok=None,  # KW publica también fuera de Granada: se comprueba por municipio
                is_sale=True,
                needs_enrich=True,
            )
            for pid in ids
        ]

    def parse_detail(self, it: Listing, html: str) -> None:
        soup = BeautifulSoup(html, "lxml")
        text = clean(soup.get_text(" "))
        title = clean(soup.title.get_text()) if soup.title else ""
        # <title>TITULO - 52.000 eur</title>
        tm = re.match(r"(.*?)\s+-\s+([\d.]+)\s*eur\s*$", title, re.I)
        if tm:
            it.title, it.price = tm.group(1), parse_price(tm.group(2))
        else:
            it.title = title
        r = rooms_from_text(text)
        if r is not None:
            it.rooms = r
        if it.price is None:
            pm = re.search(r"(\d{1,3}(?:\.\d{3})+)\s*€", text)
            it.price = parse_price(pm.group(1)) if pm else None
        lm = re.search(r"([A-Za-zÁÉÍÓÚÑÜáéíóúñü' -]{2,40}?)\s,\s([A-Za-zÁÉÍÓÚÑÜáéíóúñü' -]{2,40}?)\s*\d{1,3}(?:\.\d{3})+\s*€", text)
        if lm:
            words = lm.group(1).split()
            # el texto anterior puede arrastrar el final del título (en mayúsculas):
            # nos quedamos con las palabras que hay después de la última en mayúsculas
            for i in range(len(words) - 1, -1, -1):
                if len(words[i]) > 2 and words[i].isupper():
                    words = words[i + 1:]
                    break
            words = words[-5:]
            known = {norm(m) for m in municipios()}
            muni = " ".join(words)
            # el sufijo más largo que sea exactamente un municipio de Granada
            for k in range(len(words), 0, -1):
                cand = " ".join(words[-k:])
                if norm(cand) in known:
                    muni = cand
                    break
            it.municipality = muni.strip(" -,·")
            it.extra["location"] = f"{muni}, {lm.group(2).strip()}"
        km = re.search(r"Ref:?\s*KWK[\w-]*\s+(Comprar|Alquilar)", text)
        if km:
            it.is_sale = km.group(1) == "Comprar"
        elif "Alquilar" in text[:3000] and "Comprar" not in text[:3000]:
            it.is_sale = False
        tp = re.search(r"\b\d{7,}\s+([A-ZÁÉÍÓÚ][a-záéíóúñ]+(?: [a-záéíóúñ]+)?)\s+Ref", text)
        if tp:
            it.ptype = tp.group(1)
        og = soup.find("meta", property="og:image")
        if og and og.get("content"):
            it.photo = og["content"]
        it.m2 = it.m2 or m2_from_text(text)
        it.needs_enrich = False

    def enrich(self, it: Listing) -> None:
        self.parse_detail(it, self.http.get_text(it.url))