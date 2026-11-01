"""Prueba del flujo completo con fuentes y Telegram falsos: arranque en silencio,
aviso de novedad, bajada de precio, regla de rescate, duplicados y caídas."""
from monitor.models import Listing, id_sort_key
from monitor.runner import Monitor
from monitor.sources.base import Source
from monitor.store import Store
from monitor.utils import Http


class FakeTG:
    def __init__(self):
        self.sent = []
        self.silent = False

    def send_text(self, text, preview=False):
        self.sent.append(text)
        return True

    def send_listing(self, caption, photo):
        self.sent.append(caption)
        return True


class FakeSource(Source):
    kind = "fake"

    def __init__(self, sid, items=None):
        super().__init__(sid, sid.upper(), Http())
        self.items = items or []
        self.fail = False

    def fetch(self):
        if self.fail:
            raise RuntimeError("caída")
        return [Listing(**{**x, "source": self.id}) for x in self.items]


def L(i, price, rooms, muni="Armilla", ptype="Piso"):
    return dict(id=str(i), url=f"https://x/{i}", price=price, rooms=rooms, municipality=muni,
                ptype=ptype, sort_key=id_sort_key(i), province_ok=True)


def make(tmp_path, sources):
    cfg = {"criteria": {"max_price": 220000, "min_rooms": 3}, "fail_alert_after": 2}
    tg = FakeTG()
    return Monitor(cfg, sources, Store(tmp_path / "t.sqlite"), tg), tg


def test_flow(tmp_path):
    a = FakeSource("a", [L(1, 200000, 3), L(2, 300000, 4)])
    b = FakeSource("b", [L(10, 250000, 3, "Maracena")])
    mon, tg = make(tmp_path, [a, b])

    # 1º ciclo: se registra todo sin avisar de cada anuncio
    mon.run_cycle()
    assert len(tg.sent) == 1 and "inicializadas" in tg.sent[0]
    tg.sent.clear()

    # 2º ciclo: aparece uno nuevo que cumple en A y uno nuevo fuera de precio en B
    a.items.append(L(3, 180000, 3, "Atarfe"))
    b.items.append(L(11, 260000, 3, "Maracena"))
    mon.run_cycle()
    assert any("NUEVO" in m and "180.000" in m for m in tg.sent)
    # B no tiene nada en precio -> regla de rescate con el más reciente de 3+ hab (id 11)
    assert any("ahora mismo no tiene nada" in m and "260.000" in m for m in tg.sent)
    tg.sent.clear()

    # 3º ciclo: nada nuevo -> silencio total
    mon.run_cycle()
    assert tg.sent == []

    # 4º: bajada de precio de uno ya avisado + uno de B que baja y entra en rango
    a.items[0]["price"] = 190000
    b.items[0]["price"] = 210000
    mon.run_cycle()
    assert any("BAJADA" in m and "190.000" in m for m in tg.sent)
    assert any("NUEVO" in m and "Ha bajado" in m for m in tg.sent)
    tg.sent.clear()

    # 5º: el mismo inmueble aparece en B (misma huella) -> aviso corto de duplicado
    b.items.append(L(12, 180500, 3, "Atarfe"))
    mon.run_cycle()
    assert any("también lo anuncia" in m for m in tg.sent)
    tg.sent.clear()

    # 6º y 7º: A falla dos veces -> un único aviso de caída; al volver, aviso de recuperación
    a.fail = True
    mon.run_cycle()
    mon.run_cycle()
    assert sum("falla desde hace" in m for m in tg.sent) == 1
    a.fail = False
    mon.run_cycle()
    assert any("vuelve a funcionar" in m for m in tg.sent)


def test_digest(tmp_path):
    a = FakeSource("a", [L(1, 200000, 3), L(2, 150000, 2), L(3, 90000, 4, "Garaje", "Garaje")])
    mon, tg = make(tmp_path, [a])
    mon.run_cycle()
    tg.sent.clear()
    assert mon.send_digest() == 1
    assert "200.000" in tg.sent[0]


class EnrichSource(FakeSource):
    """Como KW: el listado no trae datos; la ficha sí."""

    def fetch(self):
        out = []
        for x in self.items:
            d = {**x, "source": self.id, "rooms": None, "price": None, "needs_enrich": True}
            out.append(Listing(**d))
        return out

    def enrich(self, it):
        x = next(i for i in self.items if i["id"] == it.id)
        it.rooms, it.price, it.needs_enrich = x["rooms"], x["price"], False


def test_backfill_is_silent_then_new_alerts(tmp_path):
    src = EnrichSource("kw", [L(1, 200000, 3), L(2, 180000, 4)])
    mon, tg = make(tmp_path, [src])
    mon.run_cycle()          # arranque: sin datos, se registran en silencio
    tg.sent.clear()
    mon.run_cycle()          # se completan las fichas de los antiguos: no debe avisar
    assert not any("NUEVO" in m for m in tg.sent)
    assert mon.store.get("kw", "1")["rooms"] == 3
    src.items.append(L(3, 150000, 3))
    mon.run_cycle()          # uno nuevo de verdad: sí avisa, con los datos de la ficha
    assert any("NUEVO" in m and "150.000" in m for m in tg.sent)