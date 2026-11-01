"""Pruebas offline con HTML/JSON real copiado de las webs (noviembre 2026).

Ejecutar:  python -m pytest -q
"""
from monitor.rules import Criteria, matches
from monitor.sources.apis import Comprarcasa, GrupoTorres, Ventaria, WpHouzez
from monitor.sources.browser_sites import Deymar, KwKinver
from monitor.sources.inmovilla import Inmovilla
from monitor.sources.simple_html import Aphome, DonPiso, Inmo30, PisosCom, Remax, Tecnocasa
from monitor.utils import Http, in_granada, parse_price, rooms_from_text

H = Http()
C = Criteria(min_price=15000)  # en los parsers probamos sin el mínimo de 100.000
C100 = Criteria()  # criterio real por defecto: 100.000–220.000 €


def test_parse_price():
    assert parse_price("212.000 €") == 212000
    assert parse_price("77000.00") == 77000
    assert parse_price("395000") == 395000
    assert parse_price("Venta 1.234.567 €") == 1234567
    assert parse_price(" 17.900 € ") == 17900


def test_rooms_and_geo():
    assert rooms_from_text("Superficie Construida 69m2, 2 Habitaciones, 1 Baño") == 2
    assert rooms_from_text("3 dorm. 89 m2") == 3
    assert rooms_from_text("Resumen 2 Habitaciones 1 Baños 68 m2") == 2
    assert in_granada("Lanjaron , Alpujarra Granadina")
    assert in_granada("Gabias (Las)")
    assert not in_granada("Mejorada del Campo")
    assert not in_granada("Madrid - Zona San Pascual")


ARRAYAN = """<div class="listarInmuebles"><img src="/fotos/1411.jpg"><div class="listarInmuebles_texto"> <div class="listado_inmuebles_precio"> 212.000 € </div> <div class="listado_inmuebles_superficie"> <p><i class="fa fa-square"></i> 155 m²</p> </div> <div class="listado_inmuebles_habitaciones"> <p><i class="fa fa-bed"></i> 3</p> </div> <div class="listado_inmuebles_transaccion"> <h4>Venta</h4> </div> <div class="listado_inmuebles_titulo" style="padding-top: 10px;"> <a href="/propiedad/venta-piso-en-ogijares/1411">Venta Piso en Ogíjares</a> </div> <div class="listado_inmuebles_poblacion"> <h2>Ogíjares - Piso</h2> </div></div></div>"""


def test_aphome():
    s = Aphome("inmoarrayan", "Inmo Arrayán", H, base_url="https://www.inmoarrayan.com")
    it = s.parse(ARRAYAN, "https://www.inmoarrayan.com/buscarInmuebles")[0]
    assert (it.id, it.price, it.rooms, it.municipality, it.ptype, it.m2) == ("1411", 212000, 3, "Ogíjares", "Piso", 155)
    assert it.url == "https://www.inmoarrayan.com/propiedad/venta-piso-en-ogijares/1411"
    assert matches(it, C)


INMOVILLA = """<html><head><base href="https://www.inmofuturo.es/"></head><body>
<div class="paginacion-ficha propiedad"><div class="paginacion-ficha-bloque1 imagenesComoBackground" cargafoto="https://fotos15.apinmo.com/6538/30630465/3-1s.jpg"> <span class="paginacion-ficha-tituloprecio">Venta 297.000 €</span> <a href="ficha/casa/granada/albaycin/6538/30630465/es/" class="irAfichaPropiedad enviarPostHog">&nbsp;</a></div>
<div class="paginacion-ficha-bloque2">Casa en Granada - Zona Albaycin, Superficie Construida 69m2, Sup. Parcela 29m2, 2 Habitaciones, 1... + INFO</div></div>
<div class="paginacion-ficha propiedad"><div class="paginacion-ficha-bloque1" cargafoto="https://fotos15.apinmo.com/6538/30588651/3-1s.jpg"> <span>Venta 169.000 €</span> <a href="ficha/planta-baja/ogijares/zona-metropolitana/6538/30588651/es/" class="irAfichaPropiedad">&nbsp;</a></div>
<div>Planta baja en Ogijares - Zona Zona metropolitana, Superficie Construida 83m2, 3 Habitaciones, 1 Baño + INFO</div></div>
<div class="paginacion-ficha propiedad"><div class="paginacion-ficha-bloque1"> <span>Venta 149.000 €</span> <a href="ficha/piso/granada/zaidin/6538/30587924/es/" class="irAfichaPropiedad">&nbsp;</a></div>
<div>Piso en Granada - Zona Zaidin, Superficie Construida 90m2, Ascensor... + INFO</div></div>
</body></html>"""


def test_inmovilla():
    s = Inmovilla("inmofuturo", "Inmofuturo", H, base_url="https://www.inmofuturo.es")
    items = s.parse_list(INMOVILLA, "https://www.inmofuturo.es/venta/?orden=5")
    assert [i.id for i in items] == ["30630465", "30588651", "30587924"]
    a, b, c = items
    assert a.url == "https://www.inmofuturo.es/ficha/casa/granada/albaycin/6538/30630465/es/"
    assert (a.price, a.rooms, a.municipality, a.ptype) == (297000, 2, "Granada", "Casa")
    assert (b.price, b.rooms, b.municipality) == (169000, 3, "Ogijares")
    assert matches(b, C) and not matches(a, C)
    assert c.rooms is None and c.needs_enrich  # descripción cortada: hay que abrir la ficha


def test_inmovilla_frame_geo():
    html = (INMOVILLA.replace("ficha/planta-baja/ogijares/zona-metropolitana", "ficha/planta-baja/mejorada-del-campo/parque")
            .replace("Planta baja en Ogijares - Zona Zona metropolitana", "Planta baja en Mejorada del Campo - Zona Parque"))
    s = Inmovilla("neo", "Neo", H, base_url="https://www.webparainmobiliarias.com.es/frame-clientes/9329", geo_check=True)
    b = s.parse_list(html, "x")[1]
    assert b.province_ok is None and not matches(b, C)  # Mejorada del Campo (Madrid) se descarta


REMAX = """<div class="layer-wrapper"> <div class="layer-media"> <a href="../buscador-de-inmuebles/venta/casa/granada/villanueva-mesia/todos/CIMA01237/"><img src="https://fotos15.apinmo.com/11231/30623651/4-1.jpg"></a></div> <div class="layer-content"><div class="datos_inmueble_wrapper"> <div class="inmueble-detalle-precio"> 190.000 € </div> <div class="inmueble-detalle-nombre"> <a href="../buscador-de-inmuebles/venta/casa/granada/villanueva-mesia/todos/CIMA01237/"> Casa en venta, Villanueva Mesía, Granada </a> </div> <div class="inmueble-detalle-datos"> 5 hab&nbsp;&nbsp; </div> <div class="inmueble-detalle-datos"> 3 baños </div> <div class="inmueble-detalle-datos"> 596 m<sup>2</sup> </div></div></div></div>"""


def test_remax():
    s = Remax("remax", "Remax", H, base_url="https://www.remaxcima.es")
    it = s.parse(REMAX, "https://www.remaxcima.es/buscador-de-inmuebles/venta/todos/granada/")[0]
    assert it.id == "CIMA01237"
    assert it.url == "https://www.remaxcima.es/buscador-de-inmuebles/venta/casa/granada/villanueva-mesia/todos/CIMA01237/"
    assert (it.price, it.rooms, it.municipality, it.ptype, it.province_ok) == (190000, 5, "Villanueva Mesía", "Casa", True)


ZAFIRO = """<div class="media"><div class="media-left"><a href="/detalle/en_venta/garaje/granada/armilla/armilla_san_miguel/63373675239.993459/"></a><div class="img" style="background-image:url('https://fotoshs.imghs.net/med/1.jpg');"></div></div><div class="media-body"><h2>Garaje en San Miguel - REF.: 000429</h2><div class="cont-precio"> <a href="" class="precio"> 17.900 € </a> </div></div></div>
<div class="media"><div class="media-left"><a href="/detalle/en_venta/piso/granada/las_gabias/aljomahima_ermita/65871757305.993459/"></a></div><div class="media-body"><h2>Piso en Aljomahima - REF.: VE-ON26</h2><div class="cont-precio"> <a href="" class="precio"> 175.000 € </a> <span class="bajaPrecio">¡Ha bajado 10.000 €!</span></div></div></div>"""


def test_pisoscom():
    s = PisosCom("zafiro", "Zafiro", H, base_url="https://www.inmozafiro.com")
    g, p = s.parse(ZAFIRO, "https://www.inmozafiro.com/buscador/en_venta/")
    assert (g.ptype, g.price) == ("garaje", 17900)
    assert (p.ptype, p.price, p.municipality, p.needs_enrich) == ("piso", 175000, "Las Gabias", True)
    assert p.sort_key < g.sort_key  # el primero de la página es el "más reciente"


TECNOCASA = """<div class="estate-card"><a href="https://www.tecnocasa.es/venta/piso/granada/granada/666222.html"><img src="https://cdn-media.medialabtc.it/x.jpeg"><div class="estate-card-price"><div class="estate-card-current-price"> 142.900 € </div></div><h3 class="estate-card-title"> Piso en venta </h3> <h4 class="estate-card-subtitle"> Granada, Almanjayar </h4><div class="estate-card-data-element estate-card-rooms"><span>3 dorm.</span></div><div class="estate-card-data-element estate-card-surface"><span>89 m<sup>2</sup></span></div></a></div>"""


def test_tecnocasa():
    s = Tecnocasa("tecnocasa", "Tecnocasa", H)
    it = s.parse(TECNOCASA, "https://www.tecnocasa.es/venta/inmuebles/andalucia/granada.html")[0]
    assert (it.id, it.price, it.rooms, it.m2, it.municipality, it.ptype) == ("666222", 142900, 3, 89, "Granada", "Piso")
    assert matches(it, C)


DONPISO = """<div class="row"><div class="col col-md-4"><a href="/pisos-y-casas/306157_piso-en-venta-granada"><img src="/767-306157-751_sfoto.jpg"></a><div><a href="/pisos-y-casas/306157_piso-en-venta-granada">1 / 12 Plano Piso en venta en Granada / Azacayas - Centro - Granada</a> 219.000 € 43 m² 1 hab. 5.046 €/m² Asc. 1ª planta</div></div>
<div class="col col-md-4"><a href="/pisos-y-casas/306200_casa-en-venta-atarfe">1 / 25 Casa Aislada en venta en Gabias (Las) / Cortijo</a> <span>185.000 €</span> 120 m² 4 hab. 1.541 €/m²</div></div>"""


def test_donpiso():
    s = DonPiso("donpiso", "DonPiso", H)
    a, b = s.parse(DONPISO, "https://www.donpiso.com/venta-casas-y-pisos/granada/listado")
    assert (a.id, a.price, a.rooms, a.municipality, a.ptype) == ("306157", 219000, 1, "Granada", "Piso")
    assert (b.id, b.price, b.rooms, b.municipality, b.ptype) == ("306200", 185000, 4, "Gabias (Las)", "Casa Aislada")
    assert matches(b, C) and not matches(a, C)


INMO30 = """<a href="/inmuebles/huetor-vega-409/"><img src="/media/ve642.jpg"><span class="referencia">Ref: ve642</span><h3>HUETOR VEGA</h3><div><span class="color-red tachado">Antes:159.000 € </span><span>Precio venta: 149.900 € </span></div>
<div class="row"><div><span class="icon-caracteristicas"> <i class="fas fa-bed fa-1x"></i> 3 </span></div><div><span class="icon-caracteristicas"> <i class="fas fa-bath fa-1x"></i> 2 </span></div><div><span class="icon-caracteristicas"><i class="fas fa-warehouse fa-1x"></i> 130m<sup>2</sup> </span></div></div></a>
<a href="/inmuebles/huetor-vega-408/"><span>Ref: ve641</span><h3>HUETOR VEGA</h3><span>Antes:14.000 € </span><span>Precio venta: 12.000 € </span> <span class="icon-caracteristicas"><i class="fas fa-warehouse fa-1x"></i> 9m<sup>2</sup> </span></a>"""


def test_inmo30():
    s = Inmo30("i30", "Inmo 3.0", H, base_url="https://www.inmobiliaria30.com")
    a, b = s.parse(INMO30, "https://www.inmobiliaria30.com/quiero-comprar/")
    assert (a.id, a.price, a.rooms, a.m2, a.municipality) == ("409", 149900, 3, 130, "Huetor Vega")
    assert (b.price, b.rooms, b.m2) == (12000, None, 9)
    assert matches(a, C) and not matches(b, C)


DEYMAR = """<div class="room-item"><a id="link_79177791771111" href="https://deymar.es/venta-comprar/piso/granada/las-gabias/gabia-grande/venta-comprar-piso-granada-las-gabias-gabia-grande-1111.html"></a> 165.000 € Piso Venta Gabia Grande, Las Gabias 95m² 2 1 ¡TU NUEVO HOGAR! +INFO Ref. 1111</div>
<div class="room-item"><a href="https://deymar.es/venta-comprar/casa/granada/las-gabias/centro/venta-comprar-casa-granada-las-gabias-centro-1110.html"></a> 199.500 € Casa Venta Centro, Las Gabias 115m² 83m² 4 2 CASA EN PLENO CENTRO +INFO Ref. 1110</div>
<div class="room-item"><a href="https://deymar.es/alquiler/piso/granada/las-gabias/centro/alquiler-piso-1106.html"></a> 650 € Piso Alquiler Centro, Las Gabias 69m² 2 1 PISO AMUEBLADO +INFO Ref. 1106</div>
<div class="room-item"><a href="https://deymar.es/venta-comprar/duplex/granada/cullar-vega/centro/x-1099.html"></a> REBAJADO 179.500 € Dúplex Venta Centro, Cullar Vega 80m² 3 2 ¡Descubre! +INFO Ref. 1099</div>"""


def test_deymar():
    s = Deymar("deymar", "Deymar", H, base_url="https://deymar.es")
    a, b, c, d = s.parse(DEYMAR, "https://deymar.es/")
    assert (a.id, a.price, a.rooms, a.ptype, a.municipality) == ("1111", 165000, 2, "Piso", "Las Gabias")
    assert (b.price, b.rooms, b.municipality) == (199500, 4, "Las Gabias")
    assert c.is_sale is False
    assert (d.price, d.rooms, d.ptype) == (179500, 3, "Dúplex")
    assert matches(b, C) and matches(d, C) and not matches(c, C)


KW_DETAIL = """<html><head><title>🏡 ¡OPORTUNIDAD EN LANJARÓN! PISO CÉNTRICO - 66.000 eur</title>
<meta property="og:image" content="https://fotos15.inmovilla.com/2279/30642984/6-1.jpg"></head><body>
<h1>🏡 ¡OPORTUNIDAD EN LANJARÓN! PISO CÉNTRICO</h1><p>Lanjaron , Alpujarra Granadina</p><p>66.000 €</p>
<nav>Inicio Propiedades 30642984</nav><span>Apartamento</span> <span>Ref: KWK-0032-TGG</span> <span>Comprar</span> <span>Libre</span>
<div>Resumen <b>3</b> Habitaciones <b>1</b> Baños 68 m2</div></body></html>"""


def test_kw_detail():
    s = KwKinver("kw", "KW", H, base_url="https://www.kwkinver.com", geo_check=True)
    from monitor.models import Listing
    it = Listing(source="kw", id="30642984", url="https://www.kwkinver.com/es/property/30642984/", needs_enrich=True)
    s.parse_detail(it, KW_DETAIL)
    assert (it.price, it.rooms, it.municipality, it.is_sale, it.ptype) == (66000, 3, "Lanjaron", True, "Apartamento")
    assert it.title.startswith("🏡 ¡OPORTUNIDAD") and matches(it, C)
    rent = KW_DETAIL.replace("<span>Comprar</span>", "<span>Alquilar</span>")
    it2 = Listing(source="kw", id="1", url="u")
    s.parse_detail(it2, rent)
    assert it2.is_sale is False


def test_kw_ids():
    from monitor.sources.browser_sites import KW_ID_RE
    html = '<img src="https://fotos15.inmovilla.com/2279/30642984/4-1s.jpg"><img src="/_next/image?url=https%3A%2F%2Ffotos15.inmovilla.com%2F2279%2F30638570%2F4-1.jpg">'
    assert [m[1] for m in KW_ID_RE.findall(html)] == ["30642984", "30638570"]


def test_neo_reference_not_rooms():
    # "Referencia NP0110262240 Habitaciones 2" no son 40 habitaciones
    assert rooms_from_text("Venta 349.000 € Referencia NP0110262240 Habitaciones 2 Baños 2 Superficie 60 m2") == 2


INMOAIRE = """<html><head><base href="https://www.inmoaire.es"></head><body><div class="listado">
<div class="paginacion-ficha-contenedorprincipal-4"><a class="irAfichaPropiedad" href="ficha/piso/padul/south-of-spain/11736/30632229/es/"></a>
<div>Piso en Padul - Zona South of spain.</div><div>154.900 €</div><div>AIRE-P42</div><div>2</div><div>2</div><div>89 m2</div></div>
<div class="paginacion-ficha-contenedorprincipal-4"><a class="irAfichaPropiedad" href="ficha/adosado/padul/south-of-spain/11736/30495907/"></a>
<div>Adosado en Padul - Zona South of spain.</div><div>169.000 €</div><div>AIRE-P041</div><div>5</div><div>2</div><div>159 m2</div></div>
<a class="irAfichaPropiedad" href="ficha/piso/padul/south-of-spain/11736/30632229/es/">ver</a>
</div></body></html>"""


def test_inmovilla_compact_template():
    s = Inmovilla("inmoaire", "InmoAire", H, base_url="https://www.inmoaire.es")
    a, b = s.parse_list(INMOAIRE, "https://www.inmoaire.es/venta/?orden=5")
    assert a.url == "https://www.inmoaire.es/ficha/piso/padul/south-of-spain/11736/30632229/es/"
    assert (a.price, a.rooms, a.m2) == (154900, 2, 89)
    assert (b.price, b.rooms, b.ptype) == (169000, 5, "Adosado") and matches(b, C)


TECNO_JSON = """<html><body><estates-index :estates="[{&quot;ad_type&quot;:&quot;estate&quot;,&quot;id&quot;:666222,&quot;detail_url&quot;:&quot;https:\\/\\/www.tecnocasa.es\\/venta\\/piso\\/granada\\/granada\\/666222.html&quot;,&quot;images&quot;:[{&quot;url&quot;:{&quot;card&quot;:&quot;https://cdn/x.jpeg&quot;}}],&quot;surface&quot;:&quot;89 m&lt;sup&gt;2&lt;/sup&gt;&quot;,&quot;price&quot;:&quot;142.900 \\u20ac&quot;,&quot;rooms&quot;:&quot;3 dorm.&quot;,&quot;subtitle&quot;:&quot;Granada, Almanjayar &quot;,&quot;title&quot;:&quot;Piso en venta&quot;}]"></estates-index></body></html>"""


def test_tecnocasa_json():
    it = Tecnocasa("tecnocasa", "Tecnocasa", H).parse(TECNO_JSON, "https://www.tecnocasa.es/x.html")[0]
    assert (it.id, it.price, it.rooms, it.m2, it.municipality, it.ptype) == ("666222", 142900, 3, 89, "Granada", "Piso")
    assert it.url == "https://www.tecnocasa.es/venta/piso/granada/granada/666222.html" and it.photo == "https://cdn/x.jpeg"


def test_apis():
    v = Ventaria("v", "Ventaria", H).parse([
        {"id": 5245, "title": "Piso en Churriana de la Vega", "permalink": "https://ventaria.es/inmueble/x/",
         "thumbnail": {"url": "u"}, "zones": ["Churriana de la Vega"], "property_type": ["Viviendas"],
         "price": 195000, "surface": 95, "rooms": 3, "property_type_extended": "Piso"},
        {"id": 5246, "title": "Piso alquiler", "permalink": "p", "zones": ["Armilla"], "price": 750, "rooms": 3,
         "property_type_extended": "Piso"},
    ])
    assert matches(v[0], C) and not matches(v[1], C)

    g = GrupoTorres("gt", "Grupo Torres", H, base_url="https://grupotorres.com").parse([
        {"id": 6640, "idInmovilla": 30649114, "fecha": "2026-10-30T19:37:36.000Z", "habitaciones": 4,
         "precioinmo": "195000", "accion": "Vender", "titulo1": "Chalet en Monachil", "ciudadId": 27,
         "provincia": {"nombre": "Granada"}, "Zona": {"nombre": "Zona metropolitana"},
         "Tipo_Oferta": {"nombre": "Chalet", "categoriaId": 1}, "fotos": [{"url": "f"}]},
        {"id": 1, "idInmovilla": 2, "habitaciones": 3, "precioinmo": "150000", "accion": "Vender",
         "provincia": {"nombre": "Malaga"}, "Tipo_Oferta": {"nombre": "Piso", "categoriaId": 1}},
        {"id": 3, "idInmovilla": 4, "habitaciones": 0, "precioinmo": "50000", "accion": "Vender",
         "provincia": {"nombre": "Granada"}, "Tipo_Oferta": {"nombre": "Local comercial", "categoriaId": 3}},
    ], cities={27: "Monachil"})
    assert g[0].url == "https://grupotorres.com/buscador/propiedades/30649114"
    assert [matches(x, C) for x in g] == [True, False, False]
    assert (g[0].municipality, g[0].extra["zona"]) == ("Monachil", "Zona metropolitana")

    cc = Comprarcasa("cc", "Comprarcasa", H, web_id="w").parse(
        [{"id": 30482292, "reference": "V1040", "type": "Dúplex", "price": 167900, "isSell": True,
          "rooms": 3, "area": 70, "location": "Las Gabias", "locationId": 282799, "mainPhoto": "m"}],
        towns={282799: "GRANADA"})
    assert cc[0].url == "https://portalhome.comprarcasa.com/inmueble/30482292" and matches(cc[0], C)

    wp = WpHouzez("pc", "Plancasa", H).parse([{
        "id": 10, "date": "2026-11-01T00:51:06", "link": "https://plancasainmobiliaria.com/property/x/",
        "title": {"rendered": "Casa adosada en venta en Chauchina"},
        "property_meta": {"fave_property_price": ["77000.00"], "fave_property_bedrooms": ["4"]},
        "_embedded": {"wp:term": [[{"taxonomy": "property_type", "name": "Casa adosada"}],
                                  [{"taxonomy": "property_status", "name": "en venta"}],
                                  [{"taxonomy": "property_state", "name": "Granada"},
                                   {"taxonomy": "property_city", "name": "Chauchina"}]]},
    }])
    assert (wp[0].price, wp[0].rooms, wp[0].municipality) == (77000, 4, "Chauchina") and matches(wp[0], C)


def test_min_price_and_exclusions():
    from monitor.models import Listing
    base = dict(source="x", url="u", rooms=3, municipality="Armilla", province_ok=True)
    assert not matches(Listing(id="1", price=95000, ptype="Piso", **base), C100)        # < 100.000
    assert matches(Listing(id="2", price=150000, ptype="Piso", **base), C100)
    for t in ["Garaje", "Terreno urbano", "Local comercial", "Parcela", "Solar", "Nave industrial", "Trastero"]:
        assert not matches(Listing(id="3", price=150000, ptype=t, **base), C100), t
    assert matches(Listing(id="4", price=150000, ptype="Casa rústica", **base), C100)


def test_zona_cerrada():
    from monitor.models import Listing
    from monitor.rules import Criteria as Cr
    cz = Cr(min_price=100000, zona=("Las Gabias", "La Zubia", "Huétor Vega", "Maracena"))
    def L(muni, **kw):
        return Listing(source="x", id=muni, url="u", price=150000, rooms=3, ptype="Piso",
                       municipality=muni, province_ok=True, **kw)
    assert matches(L("Gabias (Las)"), cz) and matches(L("Gabia Grande"), cz)
    assert matches(L("Zubia (La)"), cz) and matches(L("Huetor Vega"), cz) and matches(L("MARACENA"), cz)
    assert not matches(L("Granada"), cz) and not matches(L("Dúrcal"), cz) and not matches(L("Motril"), cz)
    # municipio vacío: se usa la URL
    it = Listing(source="x", id="9", url="https://w.es/ficha/piso/las-gabias/centro/1/2/es/", price=150000,
                 rooms=3, ptype="Piso", province_ok=True)
    assert matches(it, cz)


GENERIC = """<html><body><nav><a href="/venta/">Comprar</a><a href="/contacto/">Contacto</a></nav>
<div class="grid">
 <article class="card"><a href="/inmueble/piso-en-armilla/1234/"><img data-src="/img/1234.jpg"></a>
  <h3>Piso en Armilla</h3><p>Armilla, Granada</p><span class="price">165.000 €</span><span>3 hab.</span><span>92 m²</span></article>
 <article class="card"><a href="/inmueble/garaje-centro/1240/"><img src="/img/1240.jpg"></a>
  <h3>Garaje en Granada</h3><span>18.000 €</span></article>
 <article class="card"><a href="/inmueble/casa-la-zubia/1250/">Casa adosada en La Zubia</a><span>210.000 €</span>
  <span>4 dormitorios</span></article>
</div></body></html>"""


def test_generic_cards():
    from monitor.sources.generic import Generic
    g = Generic("g", "G", H, base_url="https://www.ejemplo.com")
    a, b, c = g.parse(GENERIC, "https://www.ejemplo.com/venta/")
    assert (a.id, a.price, a.rooms, a.m2, a.municipality, a.ptype) == ("1234", 165000, 3, 92, "Armilla", "Piso")
    assert a.url == "https://www.ejemplo.com/inmueble/piso-en-armilla/1234/" and a.photo.endswith("/img/1234.jpg")
    assert b.ptype == "Garaje" and not matches(b, C)
    assert (c.price, c.rooms, c.municipality, c.ptype) == (210000, 4, "La Zubia", "Casa adosada")
    assert g._find_list_url(GENERIC) == "https://www.ejemplo.com/venta/"


def test_generic_detects_inmovilla():
    from monitor.sources.generic import Generic
    from monitor.sources.inmovilla import Inmovilla as Inm
    g = Generic("g", "G", H, base_url="https://www.inmobiliaria4arcos.net")
    d = g._detect('<img src="https://fotos15.apinmo.com/2307/1/1.jpg">', "https://www.inmobiliaria4arcos.net/venta.php")
    assert isinstance(d, Inm) and d.list_url() == "https://www.inmobiliaria4arcos.net/venta.php"


def test_inmovilla_old_template_links_without_class():
    html = """<html><body><div class="listado">
    <div class="item"><a href="/ficha/piso/santa-fe/centro/2307/30111111/es/"><img src="https://fotos15.apinmo.com/2307/30111111/1.jpg"></a>
     <p>Piso en Santa Fe, 3 Habitaciones, 90m2</p><p>Precio: 145.000 €</p></div>
    <div class="item"><a href="/ficha/casa/la-zubia/x/2307/30222222/es/">ver</a><p>Casa en La Zubia, 4 Habitaciones</p><p>199.000 €</p></div>
    </div></body></html>"""
    s = Inmovilla("4arcos", "4Arcos", H, base_url="https://www.inmobiliaria4arcos.net", list_path="venta.php")
    a, b = s.parse_list(html, s.list_url())
    assert (a.id, a.price, a.rooms, a.municipality) == ("30111111", 145000, 3, "Santa Fe")
    assert (b.id, b.price, b.rooms, b.municipality) == ("30222222", 199000, 4, "La Zubia")


def test_generic_detecta_subdominio_e_iframe():
    from monitor.sources.generic import Generic
    from monitor.utils import Http

    g = Generic("dn", "D&N", Http(), base_url="https://dninmobiliaria.com")
    d = g._detect('<img src="https://fotos15.apinmo.com/1/2.jpg">', "https://buscador.dninmobiliaria.com/")
    assert d.base_url == "https://buscador.dninmobiliaria.com"
    assert d.list_url() == "https://buscador.dninmobiliaria.com/venta/?orden=5"
    d = g._detect('<iframe src="https://www.webparainmobiliarias.com.es/frame-clientes/1234/"></iframe>',
                  "https://x.com/comprar")
    assert d.base_url == "https://www.webparainmobiliarias.com.es/frame-clientes/1234"


def test_zona_granada_generica_mira_url():
    from monitor.models import Listing
    from monitor.rules import in_zona

    z = ("Armilla",)
    it = Listing(source="s", id="1", url="https://x.com/propiedad/piso-en-venta-en-calle-mirasol-armilla/",
                 municipality="Granada")
    assert in_zona(it, z)
    it2 = Listing(source="s", id="2", url="https://x.com/propiedad/piso-centro/", municipality="Granada")
    assert not in_zona(it2, z)