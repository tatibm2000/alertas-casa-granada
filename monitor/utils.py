from __future__ import annotations

import logging
import re
import time
import unicodedata
from typing import Optional
from urllib.parse import urlparse

import requests

from .municipios import municipios

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)

BROWSER_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}


class BlockedError(Exception):
    """La web ha rechazado la petición (403, certificado...) y no hay navegador para reintentar."""


def _playwright_ok() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def browser_get(url: str, want_json: bool = False, timeout_ms: int = 45000) -> str:
    """Descarga una URL con Chromium sin interfaz. Se usa cuando la web bloquea a `requests`
    (403 de un cortafuegos anti-bots) o tiene el certificado SSL mal instalado.

    Para APIs JSON se abre primero la portada de la web (así el navegador pasa la comprobación
    anti-bots y obtiene sus cookies) y la API se pide desde dentro de la propia página."""
    from playwright.sync_api import sync_playwright

    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}/"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        try:
            ctx = browser.new_context(user_agent=USER_AGENT, locale="es-ES", ignore_https_errors=True)
            page = ctx.new_page()
            if want_json:
                page.goto(origin, wait_until="domcontentloaded", timeout=timeout_ms)
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:  # noqa: BLE001
                    pass
                res = page.evaluate(
                    """async (u) => {
                        const r = await fetch(u, {credentials: 'include', headers: {'Accept': 'application/json'}});
                        return {status: r.status, text: await r.text()};
                    }""",
                    url,
                )
                if res["status"] >= 400:
                    raise BlockedError(f"HTTP {res['status']} también desde el navegador: {url}")
                return res["text"]
            resp = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            if resp is not None and resp.ok:
                body = resp.text()
                if "<html" in body[:2000].lower() or "<!doctype" in body[:200].lower():
                    return body
            # Página de comprobación anti-bots: esperamos a que termine y leemos lo que quede
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:  # noqa: BLE001
                pass
            return page.content()
        finally:
            browser.close()


class Http:
    """Sesión HTTP con reintentos, cabeceras de navegador, pausa mínima entre peticiones
    al mismo dominio y, si la web bloquea, reintento con un navegador real (Playwright)."""

    def __init__(self, timeout: int = 25, min_delay: float = 1.5, retries: int = 2,
                 browser_fallback: bool = True):
        self.s = requests.Session()
        self.s.headers.update(BROWSER_HEADERS)
        self.timeout = timeout
        self.min_delay = min_delay
        self.retries = retries
        self.browser_fallback = browser_fallback
        self._last: dict[str, float] = {}
        self._blocked_hosts: set[str] = set()   # hosts que ya sabemos que bloquean a requests

    def _wait(self, url: str) -> None:
        host = urlparse(url).netloc
        last = self._last.get(host)
        if last is not None:
            delta = time.monotonic() - last
            if delta < self.min_delay:
                time.sleep(self.min_delay - delta)
        self._last[host] = time.monotonic()

    def request(self, method: str, url: str, **kw) -> requests.Response:
        kw.setdefault("timeout", self.timeout)
        err: Exception | None = None
        for attempt in range(self.retries + 1):
            self._wait(url)
            try:
                r = self.s.request(method, url, **kw)
                if r.status_code >= 500 or r.status_code == 429:
                    raise requests.HTTPError(f"HTTP {r.status_code}", response=r)
                r.raise_for_status()
                return r
            except requests.HTTPError as e:
                err = e
                code = e.response.status_code if e.response is not None else 0
                if 400 <= code < 500 and code != 429:
                    raise  # un 403/404 no se arregla reintentando
            except requests.exceptions.SSLError:
                raise
            except Exception as e:  # noqa: BLE001
                err = e
            if attempt < self.retries:
                time.sleep(3 * (attempt + 1))
        assert err is not None
        raise err

    def get(self, url: str, **kw) -> requests.Response:
        return self.request("GET", url, **kw)

    def _should_fallback(self, e: Exception) -> bool:
        if isinstance(e, requests.exceptions.SSLError):
            return True
        if isinstance(e, requests.HTTPError) and e.response is not None:
            return e.response.status_code in (401, 403, 406, 429, 500, 502, 503)
        return False

    def _with_fallback(self, url: str, want_json: bool, **kw):
        host = urlparse(url).netloc
        if host not in self._blocked_hosts:
            try:
                r = self.get(url, **kw)
                if want_json:
                    return r.json()
                if not r.encoding or r.encoding.lower() == "iso-8859-1":
                    r.encoding = r.apparent_encoding
                return r.text
            except Exception as e:  # noqa: BLE001
                if not (self.browser_fallback and self._should_fallback(e)):
                    raise
                if not _playwright_ok():
                    raise BlockedError(
                        f"{type(e).__name__}: {e} — la web bloquea las peticiones directas; "
                        f"instala Playwright para que se reintente con navegador"
                    ) from e
                log.info("%s bloquea las peticiones directas (%s): uso el navegador", host, e)
                self._blocked_hosts.add(host)
        self._wait(url)
        body = browser_get(url, want_json=want_json)
        if want_json:
            import json

            return json.loads(body)
        return body

    def get_text(self, url: str, **kw) -> str:
        return self._with_fallback(url, False, **kw)

    def get_json(self, url: str, **kw):
        headers = {**kw.pop("headers", {}), "Accept": "application/json, text/plain, */*"}
        return self._with_fallback(url, True, headers=headers, **kw)


# ---------------------------------------------------------------- parsing

def norm(text: str | None) -> str:
    """minúsculas, sin tildes, solo letras/números separados por un espacio."""
    if not text:
        return ""
    t = unicodedata.normalize("NFKD", str(text))
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return t.strip()


def parse_price(text: str | None) -> Optional[int]:
    """'212.000 €' -> 212000 ; '77000.00' -> 77000 ; '1.234.567' -> 1234567."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return int(text)
    t = str(text).replace("\xa0", " ")
    # 1) miles con punto/espacio: 212.000 / 1.234.567 / 212 000 (con decimales opcionales ,50)
    m = re.search(r"\d{1,3}(?:[.\s]\d{3})+(?:,\d{1,2})?", t)
    if m:
        whole = re.split(r",", m.group(0))[0]
        return int(re.sub(r"[^\d]", "", whole))
    # 1b) miles con coma (formato inglés): 214,000 / 1,234,567
    m = re.search(r"(?<![\d.,])\d{1,3}(?:,\d{3})+(?![\d,])", t)
    if m:
        return int(m.group(0).replace(",", ""))
    # 2) número simple con decimales opcionales: 395000 / 77000.00 / 77000,5
    m = re.search(r"\d+(?:[.,]\d{1,2})?", t)
    if m:
        return int(float(m.group(0).replace(",", ".")))
    return None


def parse_int(text) -> Optional[int]:
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return int(text)
    m = re.search(r"\d+", str(text))
    return int(m.group(0)) if m else None


# el lookbehind evita leer "NP...2240 Habitaciones" o "C-15-36323-18 Habitaciones"
# (finales de una referencia) como 40 o 18 habitaciones
ROOMS_RE = re.compile(
    r"(?<![\w.,\-/])(\d{1,2})\s*(?:habitaci(?:o|ó)n(?:es)?|hab\b\.?|dormitorios?|dorm\b\.?)", re.I
)
ROOMS_RE_INV = re.compile(r"(?:habitaciones|dormitorios)\s*:?\s*(\d{1,2})(?![\d])", re.I)


def rooms_from_text(text: str | None) -> Optional[int]:
    if not text:
        return None
    m = ROOMS_RE.search(text) or ROOMS_RE_INV.search(text)
    return int(m.group(1)) if m else None


M2_RE = re.compile(r"(\d[\d.]*)\s*m\s?(?:2|²)(?![\d])", re.I)


def m2_from_text(text: str | None) -> Optional[int]:
    if not text:
        return None
    m = M2_RE.search(text)
    if not m:
        return None
    num = m.group(1).rstrip(".")
    if re.fullmatch(r"\d+\.\d{1,2}", num):          # 89.12 m2 -> 89 (decimales, no miles)
        return int(float(num))
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", num):    # 1.033 m2 -> 1033 (miles)
        return int(num.replace(".", ""))
    return parse_int(num.replace(".", ""))


# ---------------------------------------------------------------- reglas de negocio

# Tipos que NO son vivienda (se pueden ampliar con `exclude_types` en config.yaml)
NO_VIVIENDA = [
    "garaje", "cochera", "plaza de garaje", "parking", "aparcamiento", "local", "oficina",
    "nave", "solar", "terreno", "parcela", "suelo", "finca rustica", "rustica", "rustico",
    "trastero", "edificio", "hotel", "negocio", "almacen", "industrial", "bar ", "restaurante",
]


def set_excluded_types(extra: list[str] | None) -> None:
    for w in extra or []:
        w = norm(w)
        if w and w not in NO_VIVIENDA:
            NO_VIVIENDA.append(w)


def is_vivienda(ptype: str | None, title: str | None = None) -> Optional[bool]:
    """True/False si el tipo lo deja claro; None si no hay información."""
    t = norm(ptype)
    if not t:
        t2 = norm(title)
        if not t2:
            return None
        # Solo miramos la primera palabra del título ("Garaje en San Miguel")
        first = t2.split(" ")[0]
        if any(first == w.strip() for w in ["garaje", "cochera", "local", "solar", "terreno",
                                            "parcela", "nave", "oficina", "trastero", "edificio"]):
            return False
        return None
    for w in NO_VIVIENDA:
        if w.strip() and w.strip() in t:
            # "casa rustica" o "cortijo" sí son vivienda
            if w.startswith("rustic") and ("casa" in t or "cortijo" in t or "chalet" in t):
                continue
            return False
    return True


_MUNIS = None


def _muni_patterns():
    global _MUNIS
    if _MUNIS is None:
        names = sorted({norm(m) for m in municipios()}, key=len, reverse=True)
        _MUNIS = [re.compile(r"(?:^| )" + re.escape(n) + r"(?: |$)") for n in names if n]
    return _MUNIS


def in_granada(*texts: str | None) -> bool:
    blob = " " + " ".join(norm(t) for t in texts if t) + " "
    if not blob.strip():
        return False
    return any(p.search(blob) for p in _muni_patterns())


def absolute(base: str, href: str) -> str:
    from urllib.parse import urljoin

    return urljoin(base, href)


def clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()
