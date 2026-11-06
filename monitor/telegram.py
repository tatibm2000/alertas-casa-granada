from __future__ import annotations

import html
import logging
import re
import time
from typing import Optional
from urllib.parse import urljoin

import requests

log = logging.getLogger(__name__)


class Telegram:
    """Envía mensajes a un chat (grupo) de Telegram mediante la Bot API.

    En un grupo, Telegram permite ~20 mensajes por minuto: dejamos una pausa entre
    envíos y respetamos `retry_after` si nos frena.
    """

    def __init__(self, token: str, chat_id: str, min_interval: float = 3.2, dry_run: bool = False):
        self.token = token
        self.chat_id = chat_id
        self.min_interval = min_interval
        self.dry_run = dry_run
        self._last = 0.0
        self.silent = False  # True = llega sin sonido (horas de silencio)

    @property
    def api(self) -> str:
        return f"https://api.telegram.org/bot{self.token}"

    def _call(self, method: str, payload: dict, files: Optional[dict] = None) -> Optional[dict]:
        if self.dry_run:
            extra = f" (foto: {payload.get('photo') or 'subida'})" if method == "sendPhoto" else ""
            print(f"\n[DRY-RUN telegram.{method}{extra}]\n{payload.get('caption') or payload.get('text')}\n")
            return {"ok": True}
        for attempt in range(4):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                if files:
                    form = {k: (str(v).lower() if isinstance(v, bool) else str(v)) for k, v in payload.items()}
                    r = requests.post(f"{self.api}/{method}", data=form, files=files, timeout=60)
                else:
                    r = requests.post(f"{self.api}/{method}", json=payload, timeout=30)
                data = r.json()
            except Exception as e:  # noqa: BLE001
                log.warning("Telegram %s falló (%s), reintento", method, e)
                time.sleep(5 * (attempt + 1))
                continue
            if data.get("ok"):
                return data
            retry = (data.get("parameters") or {}).get("retry_after")
            if retry:
                time.sleep(int(retry) + 1)
                continue
            # Grupo convertido en supergrupo: Telegram nos da el nuevo id
            new_id = (data.get("parameters") or {}).get("migrate_to_chat_id")
            if new_id:
                log.error("El grupo ahora es un supergrupo. Cambia TELEGRAM_CHAT_ID a %s en el .env", new_id)
                payload["chat_id"] = new_id
                continue
            log.error("Telegram %s error: %s", method, data)
            return data
        return None

    def send_text(self, text: str, preview: bool = False, chat_id: str | None = None) -> bool:
        res = self._call("sendMessage", {
            "chat_id": chat_id or self.chat_id, "text": text[:4096], "parse_mode": "HTML",
            "disable_notification": self.silent,
            "link_preview_options": {"is_disabled": not preview},
        })
        return bool(res and res.get("ok"))

    def send_photo(self, photo_url: str, caption: str) -> bool:
        res = self._call("sendPhoto", {
            "chat_id": self.chat_id, "photo": photo_url, "caption": caption[:1024], "parse_mode": "HTML",
            "disable_notification": self.silent,
        })
        return bool(res and res.get("ok"))

    def send_photo_file(self, data: bytes, filename: str, caption: str) -> bool:
        res = self._call("sendPhoto", {
            "chat_id": self.chat_id, "caption": caption[:1024], "parse_mode": "HTML",
            "disable_notification": self.silent,
        }, files={"photo": (filename, data)})
        return bool(res and res.get("ok"))

    def send_listing(self, caption: str, photo: Optional[str], page_url: Optional[str] = None) -> bool:
        """Foto + texto. Si la web no nos dio foto, se busca en la ficha (og:image).
        Si Telegram no puede descargar la foto (webs que bloquean el enlace directo),
        la descargamos nosotros y la subimos. Si nada funciona, va solo el texto."""
        if photo and photo.startswith("//"):
            photo = "https:" + photo
        if (not photo or not photo.startswith("http")) and page_url and not self.dry_run:
            photo = find_photo(page_url) or photo
        if photo and photo.startswith("http"):
            if self.send_photo(photo, caption):
                return True
            if not self.dry_run:
                data = download_image(photo, referer=page_url)
                if data and self.send_photo_file(data, "foto.jpg", caption):
                    return True
            log.warning("No se pudo mandar la foto %s: va solo el texto", photo)
        return self.send_text(caption, preview=True)

    def get_updates(self, offset: int | None = None) -> list[dict]:
        """Mensajes que ha recibido el bot (Telegram los guarda 24 h). Con offset, solo los
        posteriores a ese número, y Telegram olvida los anteriores."""
        params = {"timeout": 0}
        if offset is not None:
            params["offset"] = offset
        try:
            r = requests.get(f"{self.api}/getUpdates", params=params, timeout=30)
            return r.json().get("result", []) or []
        except Exception as e:  # noqa: BLE001
            log.warning("No se pudieron leer los mensajes del bot: %s", e)
            return []

    def set_commands(self, commands: list[tuple[str, str]]) -> bool:
        """Menú de comandos que sale al escribir "/" en Telegram."""
        res = self._call("setMyCommands", {"commands": [{"command": c, "description": d} for c, d in commands]})
        return bool(res and res.get("ok"))


def esc(s: str | None) -> str:
    return html.escape(s or "", quote=False)


_HDRS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0 Safari/537.36",
    "Accept-Language": "es-ES,es;q=0.9",
}


def find_photo(page_url: str) -> Optional[str]:
    """Foto principal de una ficha: og:image / twitter:image."""
    try:
        r = requests.get(page_url, headers=_HDRS, timeout=20)
        if r.status_code != 200:
            return None
        m = re.search(r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\'][^>]*content=["\']([^"\']+)',
                      r.text, re.I) or re.search(
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\'](?:og:image|twitter:image)', r.text, re.I)
        return urljoin(page_url, html.unescape(m.group(1))) if m else None
    except Exception:  # noqa: BLE001
        return None


def download_image(url: str, referer: Optional[str] = None) -> Optional[bytes]:
    try:
        h = dict(_HDRS, Accept="image/avif,image/webp,image/*,*/*;q=0.8")
        if referer:
            h["Referer"] = referer
        r = requests.get(url, headers=h, timeout=30)
        ct = r.headers.get("content-type", "")
        if r.status_code == 200 and ct.startswith("image/") and 0 < len(r.content) < 10_000_000:
            return r.content
    except Exception:  # noqa: BLE001
        pass
    return None
