"""Conector genérico para webs de inmobiliarias que todavía no hemos revisado a mano.

1. Abre la página de listado (``list_url``) o, si no se indica, busca en la portada el enlace
   de "venta / comprar / inmuebles".
2. Reconoce el software:
   - Inmovilla (fotos en apinmo.com, enlaces /ficha/...)  -> usa el conector de Inmovilla.
   - WordPress + Houzez (API wp-json/wp/v2/properties)    -> usa el conector de WordPress.
3. Si no es ninguno de esos, lee las "tarjetas" del HTML: cada enlace a una ficha que tenga
   cerca un precio en euros. Saca precio, habitaciones, m², tipo y municipio del texto.
4. Si la página no trae anuncios en el HTML (se pintan con JavaScript), la abre con el
   navegador (Playwright) y vuelve a intentarlo.

Después de añadir una web con este conector, comprueba con:
    python -m monitor check --source <id>
Si sale vacía o con datos raros, se le hace un conector a medida.
"""
from __future__ import annotations

import hashlib
import logging
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..models import Listing, id_sort_key
from ..municipios import municipios
from ..utils import clean, m2_from_text, norm, parse_price, rooms_from_text
from .base import Source, unique

log = logging.getLogger(__name__)

LIST_WORDS = re.compile(r"venta|comprar|compra|inmuebles|propiedades|viviendas|buscador|resultados|listado", re.I)
DETAIL_HINT = re.compile(r"ficha|inmueble|propiedad|property|detalle|vivienda|piso|casa|chalet|ref|/\d{3,}|"
                         r"atico|ático|apartamento|duplex|dúplex|adosado|pareado|estudio|loft|oportunidad|venta",
                         re.I)
NOT_DETAIL = re.compile(r"alquiler|contacto|aviso|legal|cookies|privacidad|blog|noticias|nosotros|empresa|"
                        r"servicios|vender|tasacion|valora|mailto:|tel:|whatsapp|facebook|instagram|twitter|"
                        r"linkedin|youtube|#", re.I)
TYPE_RE = re.compile(
    r"\b(piso|ático|atico|dúplex|duplex|estudio|apartamento|loft|planta baja|bajo|"
    r"casa(?: adosada| pareada| unifamiliar| rústica| de campo)?|chalet(?: adosado| pareado| independiente)?|"
    r"adosado|pareado|cortijo|villa|garaje|plaza de garaje|local(?: comercial)?|oficina|nave|solar|terreno|parcela|"
    r"trastero|edificio|finca)\b",
    re.I,
)
PRICE_RE = re.compile(r"(\d{1,3}(?:[.,\s]\d{3})+|\d{5,7})\s*(?:€|eur)", re.I)


def _tipo(*texts: str) -> str:
    """Tipo de inmueble: el primero que aparezca, sin contar los "con garaje", "y trastero"..."""
    for t in texts:
        for m in TYPE_RE.finditer(t or ""):
            antes = (t[max(0, m.start() - 5):m.start()]).lower()
            if re.search(r"\b(con|y|sin|de)\s+$", antes):
                continue
            return m.group(1).capitalize()
    return ""


class Generic(Source):
    kind = "generic"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._delegate: Source | None = None
        self._munis = sorted({m for m in municipios()}, key=len, reverse=True)

    # ------------------------------------------------------------------ fetch
    def fetch(self) -> list[Listing]:
        if self._delegate is not None:
            items = self._delegate.fetch()
            self.complete = self._delegate.complete
            return self._retag(items)

        list_url = self.opts.get("list_url")
        home_html = None
        if not list_url:
            home_html = self.http.get_text(self.base_url + "/")
            list_url = self._find_list_url(home_html) or self.base_url + "/"
            log.info("%s: página de listado detectada: %s", self.id, list_url)
        html = self.http.get_text(list_url)

        # ¿Software conocido? Delegamos y lo recordamos para los siguientes ciclos.
        delegate = self._detect(html if home_html is None else home_html + html, list_url)
        if delegate is not None:
            self._delegate = delegate
            items = delegate.fetch()
            self.complete = delegate.complete
            return self._retag(items)

        items = self.parse(html, list_url)
        if not items and self.opts.get("browser_retry", True):
            rendered, delegate = None, None
            try:
                from .browser_sites import browser_page

                with browser_page() as page:
                    page.goto(list_url, wait_until="domcontentloaded", timeout=60000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=20000)
                    except Exception:  # noqa: BLE001
                        pass
                    for _ in range(4):
                        page.mouse.wheel(0, 2500)
                        page.wait_for_timeout(700)
                    rendered = page.content()
                    # los iframes también cuentan (algunas webs meten el listado de Inmovilla en uno)
                    for fr in page.frames[1:]:
                        try:
                            rendered += f"\n<!-- iframe {fr.url} -->\n" + fr.content()
                        except Exception:  # noqa: BLE001
                            pass
                    delegate = self._detect(rendered, list_url)
                    if delegate is None:
                        items = self.parse(rendered, list_url)
                        if not items:
                            self._dump(page, rendered)
            except ImportError:
                pass
            except Exception as e:  # noqa: BLE001
                log.warning("%s: no se pudo abrir con el navegador: %s", self.id, e)
            if delegate is not None:
                self._delegate = delegate
                items = delegate.fetch()
                self.complete = delegate.complete
                return self._retag(items)
        self.complete = False
        return items

    def _dump(self, page, html: str) -> None:
        """Sin anuncios: guardamos lo que ha visto el navegador para hacerle un conector a medida."""
        from pathlib import Path

        dbg = Path("data")
        dbg.mkdir(exist_ok=True)
        (dbg / f"debug_{self.id}.html").write_text(html, encoding="utf-8")
        try:
            page.screenshot(path=str(dbg / f"debug_{self.id}.png"), full_page=True)
        except Exception:  # noqa: BLE001
            pass
        log.warning("%s: no encontré anuncios. He guardado data/debug_%s.html y .png", self.id, self.id)

    def enrich(self, it: Listing) -> None:
        if self._delegate is not None:
            self._delegate.enrich(it)
            return
        soup = BeautifulSoup(self.http.get_text(it.url), "lxml")
        og = soup.find("meta", property="og:image")
        # Fuera menús, pie y "otros inmuebles": su texto confunde (habitaciones de otro piso...)
        for tag in soup.select("header, footer, nav, aside, script, style, form, [class*=relacionad], "
                               "[class*=similar], [class*=related], [class*=destacad], [class*=footer], "
                               "[class*=menu], [id*=footer], [id*=menu]"):
            tag.decompose()
        text = clean(soup.get_text(" "))
        h1 = soup.find("h1")
        if h1 is not None:
            pos = text.find(clean(h1.get_text(" ")))
            if pos > 0:
                text = text[pos:]  # empezamos por el título del anuncio
        if it.rooms is None:
            it.rooms = rooms_from_text(text)
        if it.m2 is None:
            it.m2 = m2_from_text(text)
        if it.price is None:
            pm = PRICE_RE.search(text)
            it.price = parse_price(pm.group(1)) if pm else None
        if not it.ptype:
            it.ptype = _tipo(it.title, soup.title.get_text() if soup.title else "", text[:1500])
        if not it.municipality:
            it.municipality = self._muni(text[:3000])
        if og and og.get("content") and not it.photo:
            it.photo = og["content"]
        if "alquiler" in text[:800].lower() and "venta" not in text[:800].lower():
            it.is_sale = False
        it.needs_enrich = False

    # ------------------------------------------------------------------ detección
    def _find_list_url(self, html: str) -> str | None:
        soup = BeautifulSoup(html, "lxml")
        host = urlparse(self.base_url).netloc.replace("www.", "")
        best = None
        for a in soup.find_all("a", href=True):
            href = urljoin(self.base_url + "/", a["href"])
            if host not in urlparse(href).netloc:
                continue
            label = clean(a.get_text(" ")) + " " + href
            if re.search(r"alquil", label, re.I):
                continue
            if re.search(r"\b(comprar|venta|en venta|inmuebles en venta)\b", label, re.I):
                return href
            if best is None and LIST_WORDS.search(label):
                best = href
        return best

    def _detect(self, html: str, page_url: str) -> Source | None:
        low = html.lower()
        # Listado de Inmovilla metido en un iframe (como Neo Patrimonial)
        fm = re.search(r"(https?://[^\"'\s]+/frame-clientes/\d+)", html)
        if fm:
            from .inmovilla import Inmovilla

            log.info("%s: detectado iframe de Inmovilla (%s)", self.id, fm.group(1))
            return Inmovilla(self.id, self.name, self.http,
                             **{**self.opts, "base_url": fm.group(1), "geo_check": True})
        # La web de búsqueda puede estar en otro subdominio (buscador.midominio.com)
        u = urlparse(page_url)
        origin = f"{u.scheme}://{u.netloc}"
        if "apinmo.com" in low or "inmovilla" in low or re.search(r"/ficha/[^\"']+/\d{4,}/\d{6,}/", low):
            from .inmovilla import Inmovilla

            path = u.path.lstrip("/")
            opts = {**self.opts, "base_url": origin}
            if path:
                opts["list_path"] = path + (f"?{u.query}" if u.query else "")
            log.info("%s: detectado Inmovilla en %s", self.id, origin)
            return Inmovilla(self.id, self.name, self.http, **opts)
        if "houzez" in low and "wp-content" in low:
            from .apis import WpHouzez

            log.info("%s: detectado WordPress + Houzez", self.id)
            return WpHouzez(self.id, self.name, self.http, **{**self.opts, "base_url": origin})
        return None

    def _retag(self, items: list[Listing]) -> list[Listing]:
        for it in items:
            it.source = self.id
        return items

    # ------------------------------------------------------------------ HTML genérico
    def _muni(self, text: str) -> str:
        """Primer municipio que aparece en el texto, escrito con mayúscula (así "valor" no se
        confunde con Válor ni "peligros" con Peligros). "Granada" solo si no hay otro, porque
        las webs suelen añadir la provincia: "Piso en Armilla, Granada"."""
        raw = re.findall(r"[^\W\d_]+", text or "")
        toks = [norm(w) for w in raw]
        caps = [w[:1].isupper() for w in raw]
        if not hasattr(self, "_muni_toks"):
            self._muni_toks = [(m, norm(m).split()) for m in self._munis]
        found = []
        for m, mt in self._muni_toks:
            if not mt:
                continue
            n = len(mt)
            for i in range(len(toks) - n + 1):
                if toks[i:i + n] == mt and caps[i]:
                    if mt == ["nevada"] and i > 0 and toks[i - 1] == "sierra":
                        continue
                    found.append((i, -n, m))
                    break
        if not found:
            return ""
        others = [f for f in found if norm(f[2]) != "granada"]
        return sorted(others or found)[0][2]

    def parse(self, html: str, page_url: str) -> list[Listing]:
        soup = BeautifulSoup(html, "lxml")
        base_tag = soup.find("base", href=True)
        base = base_tag["href"] if base_tag else page_url
        host = urlparse(self.base_url or page_url).netloc.replace("www.", "")
        list_path = urlparse(page_url).path.rstrip("/")

        def detail_href(a) -> str | None:
            href = urljoin(base, a["href"]).split("#")[0]
            u = urlparse(href)
            if host not in u.netloc or NOT_DETAIL.search(href):
                return None
            if u.path.rstrip("/") in ("", list_path):
                return None
            return href if DETAIL_HINT.search(u.path + "?" + u.query) else None

        links: dict[str, list] = {}
        for a in soup.find_all("a", href=True):
            h = detail_href(a)
            if h:
                links.setdefault(h, []).append(a)

        out: list[Listing] = []
        for href, anchors in links.items():
            a = anchors[0]
            box = a
            while box.parent is not None and not PRICE_RE.search(box.get_text(" ")):
                box = box.parent
                if box.name in ("body", "html"):
                    break
            if box.name in ("body", "html"):
                continue
            # crecer mientras no se mezclen otros anuncios
            while box.parent is not None and box.parent.name not in ("body", "html"):
                hrefs = {detail_href(x) for x in box.parent.find_all("a", href=True)} - {None}
                if len(hrefs) > 1:
                    break
                box = box.parent
            hrefs = {detail_href(x) for x in box.find_all("a", href=True)} - {None}
            if len(hrefs) > 1:
                continue
            text = clean(box.get_text(" "))
            pm = PRICE_RE.search(text)
            if not pm:
                continue
            ids = re.findall(r"\d{3,}", urlparse(href).path + "?" + urlparse(href).query)
            pid = ids[-1] if ids else hashlib.md5(href.encode()).hexdigest()[:12]
            img = box.find("img")
            photo = None
            if img is not None:
                photo = img.get("data-src") or img.get("data-lazy-src") or img.get("src")
                photo = urljoin(base, photo) if photo and not photo.startswith("data:") else None
            title_el = box.find(["h2", "h3", "h4"])
            rooms = rooms_from_text(text)
            out.append(
                self.L(
                    id=pid,
                    url=href,
                    title=(a.get("title") or "").strip() or (clean(title_el.get_text(" ")) if title_el else text[:140]),
                    municipality=self._muni(text) or self._muni(urlparse(href).path.replace("-", " ")),
                    ptype=_tipo(a.get("title") or "", text),
                    price=parse_price(pm.group(1)),
                    rooms=rooms,
                    m2=m2_from_text(text),
                    photo=photo,
                    sort_key=id_sort_key(pid) if ids else "",
                    province_ok=None,
                    is_sale=not re.search(r"\balquiler\b|/mes\b|€/mes", text, re.I),
                    needs_enrich=rooms is None,
                )
            )
        # sin fecha ni id numérico: el orden de la página como "más reciente"
        n = len(out)
        for i, it in enumerate(out):
            if not it.sort_key:
                it.sort_key = f"pos{n - i:06d}"
        return unique(out)
