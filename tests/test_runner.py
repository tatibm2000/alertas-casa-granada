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

    def send_text(self, text, preview=False, chat_id=None):
        self.sent.append(text)
        self.to = getattr(self, "to", []) + [chat_id]
        return True

    def send_listing(self, caption, photo, page_url=None):
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
    assert sum("falla en los últimos" in m for m in tg.sent) == 1
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


def test_incidencias_a_chat_privado_y_en_un_mensaje(tmp_path):
    a = FakeSource("a", [L(1, 200000, 3)])
    b = FakeSource("b", [L(10, 250000, 3, "Maracena")])
    cfg = {"criteria": {"max_price": 220000, "min_rooms": 3}, "fail_alert_after": 2}
    grupo, privado = FakeTG(), FakeTG()
    mon = Monitor(cfg, [a, b], Store(tmp_path / "t.sqlite"), grupo, privado)
    mon.run_cycle()
    assert grupo.sent == [] and "inicializadas" in privado.sent[0]
    privado.sent.clear()
    a.fail = b.fail = True
    mon.run_cycle()
    mon.run_cycle()
    # dos webs caídas -> un solo mensaje con las dos, y nada al grupo
    assert len(privado.sent) == 1 and "A" in privado.sent[0] and "B" in privado.sent[0]
    assert grupo.sent == []


def test_incidencias_esperan_a_la_mañana(tmp_path):
    a = FakeSource("a", [L(1, 200000, 3)])
    cfg = {"criteria": {"max_price": 220000, "min_rooms": 3}, "fail_alert_after": 1}
    grupo, privado = FakeTG(), FakeTG()
    mon = Monitor(cfg, [a], Store(tmp_path / "t.sqlite"), grupo, privado)
    mon._quiet_now = lambda: True
    mon.run_cycle()
    a.fail = True
    mon.run_cycle()
    assert privado.sent == []          # de noche: nada
    mon._quiet_now = lambda: False
    a.fail = False
    mon.run_cycle()
    assert len(privado.sent) == 1      # por la mañana: todo junto
    assert "inicializadas" in privado.sent[0] and "vuelve a funcionar" in privado.sent[0]


def test_en_pruebas_no_se_revisa_en_ciclos(tmp_path):
    a = FakeSource("a", [L(1, 200000, 3)])
    a.opts["en_pruebas"] = True
    cfg = {"criteria": {"max_price": 220000, "min_rooms": 3}}
    tg = FakeTG()
    mon = Monitor(cfg, [a], Store(tmp_path / "t.sqlite"), tg)
    mon.run_cycle()
    assert tg.sent == [] and mon.store.state("a")["seeded"] in (None, 0)



class CmdTG(FakeTG):
    """Telegram de prueba con mensajes entrantes."""

    def __init__(self, chat_id, updates):
        super().__init__()
        self.chat_id, self.token, self.dry_run = chat_id, "x", False
        self.updates, self.offsets = updates, []

    def get_updates(self, offset=None):
        self.offsets.append(offset)
        return [u for u in self.updates if offset is None or u["update_id"] >= offset]

    def set_commands(self, commands):
        return True


def _upd(uid, chat, text):
    return {"update_id": uid, "message": {"chat": {"id": chat}, "text": text}}


def test_comando_resumen_agrupado_por_inmobiliaria(tmp_path):
    a = FakeSource("a", [L(1, 200000, 3), L(2, 150000, 4, "Armilla"), L(9, 300000, 3)])
    b = FakeSource("b", [L(5, 120000, 3, "Ogíjares")])
    c = FakeSource("c", [L(7, 500000, 4)])  # nada que cumpla: no debe salir
    a.name, b.name, c.name = "Agencia A", "Agencia B", "Agencia C"
    cfg = {"criteria": {"max_price": 220000, "min_price": 100000, "min_rooms": 3}}
    ups = [_upd(10, -100, "hola, ¿habéis visto el de Armilla?"), _upd(11, -100, "/resumen@MiBot"),
           _upd(12, -100, "/resumen"), _upd(13, 555, "/resumen"), _upd(14, -100, "/otro")]
    tg = CmdTG("-100", ups)
    mon = Monitor(cfg, [a, b, c], Store(tmp_path / "t.sqlite"), tg)
    mon.run_cycle()
    texto = "\n".join(m for m in tg.sent if "Resumen" in m)
    # un único resumen, al grupo (el 555 no está autorizado), con las 3 que cumplen
    assert sum("Resumen" in m for m in tg.sent) == 1 and "-100" in tg.to
    assert "3 viviendas en 2 inmobiliarias" in texto
    assert "Agencia A" in texto and "Agencia B" in texto and "Agencia C" not in texto
    assert texto.index("150.000") < texto.index("200.000")  # dentro, por precio
    # el siguiente ciclo no repite: lee desde el último mensaje + 1
    tg.sent.clear()
    mon.run_cycle()
    assert tg.offsets[-1] == 15 and not any("Resumen" in m for m in tg.sent)
