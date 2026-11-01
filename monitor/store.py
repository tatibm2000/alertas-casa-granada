from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import Listing

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    source TEXT NOT NULL,
    id TEXT NOT NULL,
    url TEXT,
    title TEXT,
    municipality TEXT,
    ptype TEXT,
    price INTEGER,
    rooms INTEGER,
    m2 INTEGER,
    photo TEXT,
    sort_key TEXT,
    is_sale INTEGER,
    first_seen TEXT,
    last_seen TEXT,
    prev_price INTEGER,
    active INTEGER DEFAULT 1,
    notified_match INTEGER DEFAULT 0,
    notified_fallback INTEGER DEFAULT 0,
    fingerprint TEXT,
    PRIMARY KEY (source, id)
);
CREATE INDEX IF NOT EXISTS ix_listings_fp ON listings(fingerprint);

CREATE TABLE IF NOT EXISTS source_state (
    source TEXT PRIMARY KEY,
    seeded INTEGER DEFAULT 0,
    failures INTEGER DEFAULT 0,
    empties INTEGER DEFAULT 0,
    alerted_down INTEGER DEFAULT 0,
    last_ok TEXT,
    last_error TEXT,
    last_count INTEGER
);

CREATE TABLE IF NOT EXISTS alerts (
    ts TEXT,
    kind TEXT,
    source TEXT,
    id TEXT,
    fingerprint TEXT,
    price INTEGER
);
CREATE INDEX IF NOT EXISTS ix_alerts_fp ON alerts(fingerprint);

CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""


def now() -> str:
    # mismo formato que datetime('now') de SQLite (UTC) para poder comparar como texto
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class Store:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(SCHEMA)
        self.db.commit()

    # ---------------------------------------------------------------- anuncios
    def get(self, source: str, lid: str) -> Optional[sqlite3.Row]:
        return self.db.execute("SELECT * FROM listings WHERE source=? AND id=?", (source, lid)).fetchone()

    def upsert(self, it: Listing, fingerprint: str) -> None:
        ts = now()
        prev = self.get(it.source, it.id)
        if prev is None:
            self.db.execute(
                """INSERT INTO listings (source,id,url,title,municipality,ptype,price,rooms,m2,photo,
                   sort_key,is_sale,first_seen,last_seen,prev_price,active,fingerprint)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,1,?)""",
                (it.source, it.id, it.url, it.title, it.municipality, it.ptype, it.price, it.rooms,
                 it.m2, it.photo, it.sort_key, int(it.is_sale), ts, ts, fingerprint),
            )
        else:
            prev_price = prev["price"] if (it.price is not None and prev["price"] != it.price) else prev["prev_price"]
            self.db.execute(
                """UPDATE listings SET url=?, title=?, municipality=?, ptype=?, price=?, rooms=?, m2=?,
                   photo=?, sort_key=?, is_sale=?, last_seen=?, prev_price=?, active=1, fingerprint=?
                   WHERE source=? AND id=?""",
                (it.url, it.title or prev["title"], it.municipality or prev["municipality"],
                 it.ptype or prev["ptype"],
                 it.price if it.price is not None else prev["price"],
                 it.rooms if it.rooms is not None else prev["rooms"],
                 it.m2 if it.m2 is not None else prev["m2"],
                 it.photo or prev["photo"], it.sort_key or prev["sort_key"], int(it.is_sale), ts,
                 prev_price, fingerprint, it.source, it.id),
            )

    def mark_inactive_missing(self, source: str, seen_ids: set[str]) -> None:
        rows = self.db.execute("SELECT id FROM listings WHERE source=? AND active=1", (source,)).fetchall()
        gone = [(source, r["id"]) for r in rows if r["id"] not in seen_ids]
        self.db.executemany("UPDATE listings SET active=0 WHERE source=? AND id=?", gone)

    def set_flag(self, source: str, lid: str, flag: str) -> None:
        assert flag in {"notified_match", "notified_fallback"}
        self.db.execute(f"UPDATE listings SET {flag}=1 WHERE source=? AND id=?", (source, lid))

    def mark_seeded(self, source: str, matching_ids: set[str]) -> None:
        """Arranque en silencio: nada de lo que ya existe dispara la regla de rescate, y lo que
        ya cumple el filtro queda como avisado. Lo que hoy está fuera de precio sí avisará
        si más adelante baja y entra en rango."""
        self.db.execute("UPDATE listings SET notified_fallback=1 WHERE source=?", (source,))
        self.db.executemany("UPDATE listings SET notified_match=1 WHERE source=? AND id=?",
                            [(source, i) for i in matching_ids])

    def count(self, source: str | None = None, active_only: bool = True) -> int:
        q = "SELECT COUNT(*) FROM listings WHERE 1=1"
        args: list = []
        if source:
            q += " AND source=?"
            args.append(source)
        if active_only:
            q += " AND active=1"
        return self.db.execute(q, args).fetchone()[0]

    # ---------------------------------------------------------------- avisos
    def log_alert(self, kind: str, it: Listing, fingerprint: str) -> None:
        self.db.execute("INSERT INTO alerts VALUES (?,?,?,?,?,?)",
                        (now(), kind, it.source, it.id, fingerprint, it.price))

    def recent_alert_for_fp(self, fingerprint: str, exclude_source: str, days: int = 45) -> Optional[sqlite3.Row]:
        if not fingerprint:
            return None
        return self.db.execute(
            """SELECT a.*, l.url FROM alerts a LEFT JOIN listings l ON l.source=a.source AND l.id=a.id
               WHERE a.fingerprint=? AND a.source<>? AND a.ts >= datetime('now', ?)
               ORDER BY a.ts DESC LIMIT 1""",
            (fingerprint, exclude_source, f"-{days} days"),
        ).fetchone()

    def alerts_since(self, hours: int = 24) -> int:
        return self.db.execute(
            "SELECT COUNT(*) FROM alerts WHERE ts >= datetime('now', ?)", (f"-{hours} hours",)
        ).fetchone()[0]

    # ---------------------------------------------------------------- estado de fuentes
    def state(self, source: str) -> sqlite3.Row:
        self.db.execute("INSERT OR IGNORE INTO source_state(source) VALUES (?)", (source,))
        return self.db.execute("SELECT * FROM source_state WHERE source=?", (source,)).fetchone()

    def update_state(self, source: str, **fields) -> None:
        self.state(source)
        cols = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE source_state SET {cols} WHERE source=?", (*fields.values(), source))

    def all_states(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM source_state ORDER BY source").fetchall()

    def get_meta(self, k: str) -> Optional[str]:
        r = self.db.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return r["v"] if r else None

    def set_meta(self, k: str, v: str) -> None:
        self.db.execute("INSERT INTO meta(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))

    def current_matches(self, max_price: int, min_rooms: int) -> list[sqlite3.Row]:
        return self.db.execute(
            """SELECT * FROM listings WHERE active=1 AND is_sale=1 AND price IS NOT NULL AND price<=?
               AND rooms>=? ORDER BY price""",
            (max_price, min_rooms),
        ).fetchall()

    def commit(self) -> None:
        self.db.commit()

    def close(self) -> None:
        self.db.commit()
        try:
            # vuelca el WAL al archivo principal: la BD queda en un solo fichero (útil para copiarla)
            self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass
        self.db.close()