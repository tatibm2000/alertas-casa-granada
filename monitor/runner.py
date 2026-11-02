from __future__ import annotations

import json
import logging
import os
import signal
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from . import messages as msg
from .models import Listing
from .rules import Criteria, fallback_ok, fingerprint, matches, maybe_relevant
from .sources.base import Source
from .store import Store
from .telegram import Telegram, esc

log = logging.getLogger("monitor")


def playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def row_to_listing(r) -> Listing:
    return Listing(
        source=r["source"], id=r["id"], url=r["url"], title=r["title"] or "",
        municipality=r["municipality"] or "", ptype=r["ptype"] or "", price=r["price"],
        rooms=r["rooms"], m2=r["m2"], photo=r["photo"], sort_key=r["sort_key"] or "",
        is_sale=bool(r["is_sale"]),
    )


class Monitor:
    def __init__(self, cfg: dict, sources: list[Source], store: Store, tg: Telegram,
                 admin: Telegram | None = None):
        self.cfg = cfg
        self.sources = sources
        self.store = store
        self.tg = tg                  # grupo: solo pisos
        self.admin = admin or tg      # chat privado: incidencias y estado del monitor
        self.incidents: list[str] = []
        self.c = Criteria.from_cfg(cfg.get("criteria", {}))
        self.names = {s.id: s.name for s in sources}
        self.tz = ZoneInfo(cfg.get("timezone", "Europe/Madrid"))
        self.enrich_limit = int(cfg.get("enrich_limit_per_source", 12))
        self.fail_alert_after = int(cfg.get("fail_alert_after", 3))
        # El número de ciclo se guarda en la BD: así "every" y el recorrido completo de Tecnocasa
        # funcionan igual con el bucle 24/7 que con ejecuciones sueltas (GitHub Actions).
        try:
            self.cycle = int(store.get_meta("cycle") or 0)
        except (TypeError, ValueError):
            self.cycle = 0
        self._stop = False
        self._has_pw = playwright_available()
        self.seeded_now: list[tuple[str, int]] = []

    # ------------------------------------------------------------------ bucle
    def run_forever(self) -> None:
        interval = int(self.cfg.get("interval_minutes", 15)) * 60
        signal.signal(signal.SIGTERM, lambda *_: self.stop())
        signal.signal(signal.SIGINT, lambda *_: self.stop())
        log.info("Monitor en marcha: %d fuentes, cada %d min", len(self.sources), interval // 60)
        while not self._stop:
            started = time.monotonic()
            try:
                self.run_cycle()
            except Exception:  # noqa: BLE001
                log.exception("Error inesperado en el ciclo")
            elapsed = time.monotonic() - started
            log.info("Ciclo %d terminado en %.0f s", self.cycle, elapsed)
            sleep_for = max(30, interval - elapsed)
            end = time.monotonic() + sleep_for
            while not self._stop and time.monotonic() < end:
                time.sleep(2)
        self.store.close()
        log.info("Monitor detenido")

    def stop(self) -> None:
        self._stop = True

    def run_cycle(self, only: str | None = None) -> None:
        self.cycle += 1
        self.store.set_meta("cycle", str(self.cycle))
        self.seeded_now = []
        self.tg.silent = self._quiet_now()
        for src in self.sources:
            if only and src.id != only:
                continue
            if not self._here(src):
                continue  # web que bloquea a los servidores de GitHub: solo se revisa en local
            every = int(src.opts.get("every", 1))
            if not only and (self.cycle - 1) % every != 0:
                continue
            src.cycle_hint = self.cycle
            if src.needs_browser and not self._has_pw:
                log.warning("%s necesita Playwright y no está instalado: se salta", src.id)
                continue
            self.run_source(src)
            self.store.commit()
        if self.seeded_now:
            total = sum(n for _, n in self.seeded_now)
            fuentes = ", ".join(esc(self.names[s]) for s, _ in self.seeded_now)
            self.incidents.append(
                f"✅ <b>Fuentes inicializadas</b>: {fuentes}\n"
                f"{total} anuncios registrados como punto de partida. "
                f"A partir de ahora avisaré solo de las novedades "
                f"(≤ {msg.eur(self.c.max_price)}, {self.c.min_rooms}+ hab)."
            )
        self.flush_incidents()
        self.heartbeat()
        self.store.commit()

    # ------------------------------------------------------------------ una fuente
    def run_source(self, src: Source) -> None:
        state = self.store.state(src.id)
        try:
            items = src.fetch()
        except Exception as e:  # noqa: BLE001
            self._on_failure(src, state, f"{type(e).__name__}: {e}")
            return
        if not items:
            empties = (state["empties"] or 0) + 1
            self.store.update_state(src.id, empties=empties)
            log.warning("%s: 0 anuncios (%d veces seguidas)", src.id, empties)
            if empties >= self.fail_alert_after and not state["alerted_down"]:
                self.incidents.append(
                    f"⚠️ <b>{esc(src.name)}</b>: 0 anuncios en los últimos {empties} intentos "
                    f"(¿bloqueo o cambio de web?)"
                )
                self.store.update_state(src.id, alerted_down=1)
            return
        self._on_success(src, state, len(items))

        seeding = not state["seeded"]
        budget = self.enrich_limit
        prevs = {it.id: self.store.get(src.id, it.id) for it in items}

        # 1) completar con lo que ya sabíamos
        for it in items:
            prev = prevs[it.id]
            if prev is not None:
                if it.rooms is None and prev["rooms"] is not None:
                    it.rooms = prev["rooms"]
                if it.price is None and prev["price"] is not None:
                    it.price = prev["price"]
                if it.m2 is None and prev["m2"] is not None:
                    it.m2 = prev["m2"]
                if it.rooms is not None and it.price is not None:
                    it.needs_enrich = False

        # 2) abrir fichas para lo que falta (habitaciones/precio). Primero los nuevos y luego,
        #    poco a poco en cada ciclo, los que quedaron sin datos al arrancar (p. ej. KW Kinver).
        if not seeding:
            pending = [it for it in items if it.needs_enrich and maybe_relevant(it, self.c)]
            pending.sort(key=lambda x: (prevs[x.id] is None, x.sort_key or ""), reverse=True)
            for it in pending[:budget]:
                budget -= 1
                self._enrich(src, it)

        for it in items:
            self.store.upsert(it, fingerprint(it))
        if src.complete:
            self.store.mark_inactive_missing(src.id, {it.id for it in items})

        if seeding:
            # lo que ya cumple y lo que aún no tiene datos completos se considera "ya visto":
            # cuando se rellenen sus datos en ciclos siguientes no se avisará como nuevo
            unknown = {it.id for it in items if it.rooms is None or it.price is None}
            self.store.mark_seeded(src.id, {it.id for it in items if matches(it, self.c)} | unknown)
            self.store.update_state(src.id, seeded=1)
            self.seeded_now.append((src.id, len(items)))
            log.info("%s: inicializada con %d anuncios", src.id, len(items))
            return

        # 3) avisos de anuncios que cumplen
        any_match = False
        for it in items:
            if not matches(it, self.c):
                continue
            any_match = True
            prev = prevs[it.id]
            row = self.store.get(src.id, it.id)
            if prev is None:
                self._alert_new(src, it)
            elif not row["notified_match"]:
                note = ""
                if prev["price"] and it.price and it.price < prev["price"]:
                    note = f"📉 Ha bajado de {msg.eur(prev['price'])} y ahora entra en el rango."
                self._alert_new(src, it, note)
            elif prev["price"] and it.price and it.price < prev["price"] * (1 - self.c.price_drop_min_pct / 100):
                self.tg.send_listing(msg.price_drop(it, prev["price"], src.name), it.photo, it.url)
                self.store.log_alert("drop", it, fingerprint(it))

        # 4) regla de rescate: si este portal no tiene nada en precio, el más reciente con 3+ hab
        if self.c.fallback and not any_match:
            self._fallback(src, items, budget)

    # ------------------------------------------------------------------ helpers
    def _enrich(self, src: Source, it: Listing) -> None:
        try:
            src.enrich(it)
        except Exception as e:  # noqa: BLE001
            log.warning("%s: no se pudo abrir la ficha %s: %s", src.id, it.url, e)

    def _alert_new(self, src: Source, it: Listing, note: str = "") -> None:
        fp = fingerprint(it)
        dup = self.store.recent_alert_for_fp(fp, exclude_source=src.id)
        if dup is not None:
            self.tg.send_text(msg.duplicate(it, src.name, self.names.get(dup["source"], dup["source"]), dup["url"]))
            self.store.log_alert("dup", it, fp)
        else:
            self.tg.send_listing(msg.new_listing(it, src.name, note), it.photo, it.url)
            self.store.log_alert("new", it, fp)
        self.store.set_flag(src.id, it.id, "notified_match")

    def _fallback(self, src: Source, items: list[Listing], budget: int) -> None:
        ordered = sorted(items, key=lambda x: x.sort_key or "", reverse=True)
        top = None
        for it in ordered[:25]:
            if it.rooms is None and it.needs_enrich and budget > 0 and maybe_relevant(it, self.c):
                budget -= 1
                self._enrich(src, it)
                self.store.upsert(it, fingerprint(it))
            if fallback_ok(it, self.c):
                top = it
                break
        if top is None:
            return
        row = self.store.get(src.id, top.id)
        if row["notified_fallback"] or row["notified_match"]:
            return
        self.tg.send_listing(msg.fallback(top, src.name, self.c.max_price, self.c.min_rooms), top.photo, top.url)
        self.store.log_alert("fallback", top, fingerprint(top))
        self.store.set_flag(src.id, top.id, "notified_fallback")

    def _on_failure(self, src: Source, state, err: str) -> None:
        failures = (state["failures"] or 0) + 1
        log.warning("%s falló (%d seguidas): %s", src.id, failures, err)
        self.store.update_state(src.id, failures=failures, last_error=err[:500])
        if failures >= self.fail_alert_after and not state["alerted_down"]:
            self.incidents.append(
                f"⚠️ <b>{esc(src.name)}</b>: falla en los últimos {failures} intentos\n<code>{esc(err[:200])}</code>"
            )
            self.store.update_state(src.id, alerted_down=1)

    def _on_success(self, src: Source, state, n: int) -> None:
        if state["alerted_down"]:
            self.incidents.append(f"✅ <b>{esc(src.name)}</b> vuelve a funcionar ({n} anuncios)")
        self.store.update_state(src.id, failures=0, empties=0, alerted_down=0,
                                last_ok=datetime.now(self.tz).isoformat(timespec="seconds"), last_count=n)
        log.info("%s: %d anuncios", src.id, n)

    @staticmethod
    def _here(src: Source) -> bool:
        """¿Se revisa esta web aquí? (las local_only no se revisan en GitHub Actions)"""
        return not (src.opts.get("local_only") and os.environ.get("GITHUB_ACTIONS"))

    def _active_ids(self) -> set[str]:
        return {s.id for s in self.sources if self._here(s)}

    def flush_incidents(self) -> None:
        """Todas las incidencias del ciclo en UN mensaje al chat privado. En horas de
        silencio no se manda nada: se guardan y salen en el primer ciclo de la mañana."""
        try:
            pending = json.loads(self.store.get_meta("pending_incidents") or "[]")
        except ValueError:
            pending = []
        pending += self.incidents
        self.incidents = []
        if not pending:
            return
        if self._quiet_now():
            self.store.set_meta("pending_incidents", json.dumps(pending[-40:]))
            return
        now = datetime.now(self.tz)
        text = f"🛠 <b>Incidencias del monitor</b> ({now:%d/%m %H:%M})\n\n" + "\n\n".join(pending)
        if self.admin.send_text(text[:4000]):
            self.store.set_meta("pending_incidents", "[]")
        else:
            self.store.set_meta("pending_incidents", json.dumps(pending[-40:]))

    def _quiet_now(self) -> bool:
        q = self.cfg.get("quiet_hours")  # p.ej. [0, 8] -> de 00:00 a 08:00 llegan sin sonido
        if not q:
            return False
        h = datetime.now(self.tz).hour
        start, end = int(q[0]), int(q[1])
        return start <= h < end if start < end else (h >= start or h < end)

    def heartbeat(self) -> None:
        hour = self.cfg.get("heartbeat_hour")
        if hour is None:
            return
        now = datetime.now(self.tz)
        today = now.date().isoformat()
        if now.hour < int(hour) or self.store.get_meta("last_heartbeat") == today:
            return
        # solo las webs que se revisan aquí (fuera las desactivadas y las local_only en GitHub)
        activas = self._active_ids()
        states = [s for s in self.store.all_states() if s["source"] in activas]
        ok = [s for s in states if not s["alerted_down"]]
        down = [self.names.get(s["source"], s["source"]) for s in states if s["alerted_down"]]
        n_match = len(self.matches_now())
        text = (
            f"🟢 <b>Monitor activo</b> ({now:%d/%m %H:%M})\n"
            f"Fuentes OK: {len(ok)}/{len(states)}\n"
            f"Anuncios vigilados: {self.store.count()}\n"
            f"Ahora mismo cumplen el filtro: {n_match}\n"
            f"Avisos enviados en 24 h: {self.store.alerts_since(24)}"
        )
        if down:
            text += "\n⚠️ Con problemas: " + ", ".join(esc(d) for d in down)
        self.admin.send_text(text)
        self.store.set_meta("last_heartbeat", today)

    def matches_now(self) -> list[Listing]:
        rows = self.store.current_matches(self.c.max_price, self.c.min_rooms)
        out = []
        for r in rows:
            it = row_to_listing(r)
            src = next((s for s in self.sources if s.id == it.source), None)
            if src is None or not self._here(src):
                continue  # web desactivada o que aquí no se revisa: sus datos pueden estar viejos
            it.province_ok = None if src.geo_check else True
            if matches(it, self.c):
                out.append(it)
        return out

    def send_digest(self) -> int:
        items = sorted(self.matches_now(), key=lambda x: (x.price or 0))
        if not items:
            self.tg.send_text("No hay ahora mismo ningún anuncio que cumpla el filtro.")
            return 0
        header = (f"📋 <b>Resumen</b>: {len(items)} viviendas ≤ {msg.eur(self.c.max_price)} "
                  f"con {self.c.min_rooms}+ hab\n\n")
        lines = [
            f'• <b>{msg.eur(i.price)}</b> · {esc(msg.tipo(i))} · {i.rooms} hab{f" · {i.m2} m²" if i.m2 else ""} · {esc(i.municipality)} '
            f'({esc(self.names.get(i.source, i.source))}) <a href="{esc(i.url)}">ver</a>'
            for i in items
        ]
        chunk, size = [], len(header)
        for line in lines:
            if size + len(line) > 3800:
                self.tg.send_text(header + "\n".join(chunk))
                header, chunk, size = "", [], 0
            chunk.append(line)
            size += len(line) + 1
        if chunk:
            self.tg.send_text(header + "\n".join(chunk))
        return len(items)
