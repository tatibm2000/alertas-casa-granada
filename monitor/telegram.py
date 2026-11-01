from __future__ import annotations

import html
import logging
import time
from typing import Optional

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

    def _call(self, method: str, payload: dict) -> Optional[dict]:
        if self.dry_run:
            print(f"\n[DRY-RUN telegram.{method}]\n{payload.get('caption') or payload.get('text')}\n")
            return {"ok": True}
        for attempt in range(4):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
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

    def send_text(self, text: str, preview: bool = False) -> bool:
        res = self._call("sendMessage", {
            "chat_id": self.chat_id, "text": text[:4096], "parse_mode": "HTML",
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

    def send_listing(self, caption: str, photo: Optional[str]) -> bool:
        if photo and photo.startswith("http"):
            if self.send_photo(photo, caption):
                return True
            # la foto puede fallar (formato, tamaño, hotlink): mandamos solo el texto
        return self.send_text(caption, preview=True)

    def get_updates(self) -> list[dict]:
        r = requests.get(f"{self.api}/getUpdates", timeout=30)
        return r.json().get("result", [])


def esc(s: str | None) -> str:
    return html.escape(s or "", quote=False)
