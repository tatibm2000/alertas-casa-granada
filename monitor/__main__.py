"""Uso:

    python -m monitor run                 # bucle 24/7 (lo que lanza systemd)
    python -m monitor once                # un solo ciclo y termina
    python -m monitor check [--source X]  # prueba los conectores sin guardar ni enviar nada
    python -m monitor telegram-test       # manda un mensaje de prueba al grupo
    python -m monitor chat-id             # muestra los chats que ve el bot (para sacar el id del grupo)
    python -m monitor resumen             # manda al grupo la lista de lo que cumple ahora mismo
    python -m monitor estado              # estado de cada fuente
    python -m monitor ejemplo [--source X] # manda al grupo un anuncio real que cumple, con el formato de aviso

Opciones comunes: --config config.yaml  --dry-run (imprime en vez de enviar a Telegram)
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import yaml

from .rules import Criteria, base_ok, geo_ok, matches, vivienda
from .runner import Monitor, playwright_available
from .sources import build_sources
from .store import Store
from .telegram import Telegram
from .utils import Http

ROOT = Path(__file__).resolve().parent.parent


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="monitor")
    ap.add_argument("command", choices=["run", "once", "check", "telegram-test", "chat-id", "resumen", "estado", "ejemplo"])
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--source", help="limitar a una fuente (id de config.yaml)")
    ap.add_argument("--dry-run", action="store_true", help="no envía a Telegram, imprime por pantalla")
    ap.add_argument("--fichas", type=int, default=6,
                    help="check: fichas máximas a abrir por web para completar datos (0 = ninguna)")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if a.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    load_env(ROOT / ".env")
    cfg = yaml.safe_load(Path(a.config).read_text(encoding="utf-8"))

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")

    if a.command == "chat-id":
        if not token:
            print("Falta TELEGRAM_BOT_TOKEN en .env")
            return 1
        ups = Telegram(token, "").get_updates()
        chats = {}
        for u in ups:
            for key in ("message", "my_chat_member", "channel_post", "edited_message"):
                m = u.get(key)
                if m and m.get("chat"):
                    c = m["chat"]
                    chats[c["id"]] = f'{c.get("type")}: {c.get("title") or c.get("username") or c.get("first_name")}'
        if not chats:
            print("No hay mensajes recientes. Escribe algo en el grupo (p.ej. /start@TuBot) y repite.")
        for cid, desc in chats.items():
            print(f"{cid}\t{desc}")
        return 0

    if a.command != "check" and not a.dry_run and (not token or not chat):
        print("Faltan TELEGRAM_BOT_TOKEN y/o TELEGRAM_CHAT_ID en el archivo .env")
        return 1

    tg = Telegram(token, chat, dry_run=a.dry_run)
    if a.command == "telegram-test":
        ok = tg.send_text("👋 Hola, soy el monitor de viviendas de Granada. Si leéis esto, el bot está bien configurado.")
        print("Enviado" if ok else "Error enviando (revisa el token, el id y que el bot esté en el grupo)")
        return 0 if ok else 1

    http = Http()
    sources = build_sources(cfg["sources"], http)
    if a.source:
        sources = [s for s in sources if s.id == a.source]
        if not sources:
            print(f"No existe la fuente {a.source}")
            return 1

    if a.command == "check":
        return check(sources, Criteria.from_cfg(cfg.get("criteria", {})), a.fichas)
    if a.command == "ejemplo":
        return ejemplo(sources, Criteria.from_cfg(cfg.get("criteria", {})), tg, a.fichas)

    db = Path(cfg.get("database", "data/monitor.sqlite"))
    if not db.is_absolute():
        db = ROOT / db
    store = Store(db)
    mon = Monitor(cfg, sources, store, tg)

    if a.command == "run":
        mon.run_forever()
    elif a.command == "once":
        mon.run_cycle(only=a.source)
        store.close()
    elif a.command == "resumen":
        n = mon.send_digest()
        print(f"{n} anuncios en el resumen")
        store.close()
    elif a.command == "estado":
        for s in store.all_states():
            print(f'{s["source"]:16} ok={s["last_ok"]} n={s["last_count"]} fallos={s["failures"]} '
                  f'caída={"sí" if s["alerted_down"] else "no"} {s["last_error"] or ""}')
        print(f"Anuncios activos en BD: {store.count()}")
        store.close()
    return 0


def ejemplo(sources, c: Criteria, tg: Telegram, max_fichas: int = 6) -> int:
    """Busca el primer anuncio que cumple y lo manda al grupo con el formato de los avisos.
    No guarda nada en la base de datos: el aviso real llegará igualmente cuando toque."""
    from . import messages as msg

    for src in sources:
        if src.needs_browser and not playwright_available():
            continue
        try:
            items = src.fetch()
        except Exception as e:  # noqa: BLE001
            print(f"{src.name}: error ({e}), pruebo la siguiente")
            continue
        enriched = 0
        for it in sorted(items, key=lambda x: x.sort_key or "", reverse=True):
            if it.needs_enrich and enriched < max_fichas:
                try:
                    src.enrich(it)
                    enriched += 1
                except Exception:  # noqa: BLE001
                    continue
            if matches(it, c):
                text = msg.new_listing(it, src.name, "🧪 <i>Mensaje de ejemplo: así llegarán los avisos</i>")
                ok = tg.send_listing(text, it.photo)
                print(("Enviado: " if ok else "Error enviando: ") + it.url)
                return 0 if ok else 1
        print(f"{src.name}: ningún anuncio que cumpla ahora mismo, pruebo la siguiente")
    print("No he encontrado ningún anuncio que cumpla en las fuentes elegidas")
    return 1


def check(sources, c: Criteria, max_fichas: int = 6) -> int:
    """Descarga cada fuente y enseña lo que entiende el parser. No guarda ni envía nada."""
    bad = 0
    for src in sources:
        print(f"\n=== {src.name} ({src.id}, {src.kind}) ===")
        if src.needs_browser and not playwright_available():
            print("  (necesita Playwright: pip install playwright && playwright install --with-deps chromium)")
            continue
        try:
            items = src.fetch()
        except Exception as e:  # noqa: BLE001
            bad += 1
            print(f"  ERROR: {type(e).__name__}: {e}")
            continue
        if not items:
            bad += 1
        enriched = 0
        for it in sorted(items, key=lambda x: x.sort_key or "", reverse=True)[:12]:
            if it.needs_enrich and enriched < max_fichas:
                try:
                    src.enrich(it)
                    enriched += 1
                except Exception as e:  # noqa: BLE001
                    print(f"  (no se pudo abrir la ficha: {e})")
            flag = "✅" if matches(it, c) else ("·3hab" if base_ok(it, c) else "  ")
            if not vivienda(it) and it.ptype:
                flag = "✗tipo"  # garaje, terreno, local... (excluido)
            elif c.zona and not geo_ok(it, c) and (it.municipality or it.title):
                flag = "✗zona"  # fuera de los municipios elegidos
            m2 = f"{it.m2} m²" if it.m2 else "? m²"
            print(f"  {flag:5} {str(it.price or '?'):>8} €  {str(it.rooms if it.rooms is not None else '?'):>2} hab  "
                  f"{m2:>8}  {(it.ptype or '')[:14]:14} {(it.municipality or '')[:22]:22} {it.url}")
        print(f"  Total leídos: {len(items)} · cumplen: {sum(matches(i, c) for i in items)}")
    lo, hi = f"{c.min_price:,}".replace(",", "."), f"{c.max_price:,}".replace(",", ".")
    print(f"\nLeyenda: ✅ cumple ({lo}–{hi} €, {c.min_rooms}+ hab, vivienda) · "
          f"·3hab = vivienda con {c.min_rooms}+ hab fuera de precio · ✗tipo = garaje/terreno/local... excluido"
          + (" · ✗zona = fuera de los municipios elegidos" if c.zona else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())