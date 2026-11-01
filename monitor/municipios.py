"""Municipios y núcleos de población de la provincia de Granada.

Se usa solo para las fuentes que publican inmuebles de varias provincias
(Neo Patrimonial, KW Kinver, Comprarcasa...). La comparación se hace sin
tildes, en minúsculas y por palabra completa. Si echas en falta alguno,
añádelo a la lista: no hace falta tocar nada más.
"""

MUNICIPIOS = """
Agrón; Alamedilla; Albolote; Albondón; Albuñán; Albuñol; Albuñuelas; Aldeire; Alfacar;
Algarinejo; Alhama de Granada; Alhendín; Alicún de Ortega; Almegíjar; Almuñécar;
Alpujarra de la Sierra; Alquife; Arenas del Rey; Armilla; Atarfe; Baza; Beas de Granada;
Beas de Guadix; Benalúa; Benalúa de las Villas; Benamaurel; Bérchules; Bubión; Busquístar;
Cacín; Cádiar; Cájar; Calicasas; Campotéjar; Caniles; Cáñar; Capileira; Carataunas;
Cástaras; Castilléjar; Castril; Cenes de la Vega; Chauchina; Chimeneas; Churriana de la Vega;
Cijuela; Cogollos de Guadix; Cogollos de la Vega; Colomera; Cortes de Baza; Cortes y Graena;
Cuevas del Campo; Cúllar; Cúllar Vega; Darro; Dehesas de Guadix; Dehesas Viejas; Deifontes;
Diezma; Dílar; Dólar; Domingo Pérez de Granada; Dúdar; Dúrcal; El Pinar; El Valle; Escúzar;
Ferreira; Fonelas; Freila; Fuente Vaqueros; Galera; Gobernador; Gójar; Gor; Gorafe; Granada;
Guadahortuna; Guadix; Gualchos; Güéjar Sierra; Güevéjar; Huélago; Huéneja; Huéscar;
Huétor de Santillán; Huétor Santillán; Huétor Tájar; Huétor Vega; Íllora; Ítrabo; Iznalloz;
Játar; Jayena; Jérez del Marquesado; Jete; Jun; Juviles; La Calahorra; La Malahá; La Peza;
La Taha; La Zubia; Zubia; Láchar; Lanjarón; Lanjaron; Lanteira; Las Gabias; Gabias; Lecrín;
Lentegí; Lobras; Loja; Los Guájares; Lugros; Lújar; Maracena; Marchal; Moclín; Molvízar;
Monachil; Montefrío; Montejícar; Montillana; Moraleda de Zafayona; Morelábor; Motril; Murtas;
Nevada; Nigüelas; Nívar; Ogíjares; Orce; Órgiva; Otívar; Otura; Padul; Pampaneira;
Pedro Martínez; Peligros; Pinos Genil; Pinos Puente; Píñar; Polícar; Polopos; Pórtugos;
Puebla de Don Fadrique; Pulianas; Purullena; Quéntar; Rubite; Salar; Salobreña;
Santa Cruz del Comercio; Santa Fe; Soportújar; Sorvilán; Torre Cardela; Torre-Cardela;
Torrenueva Costa; Torvizcón; Trevélez; Turón; Ugíjar; Valderrubio; Valle del Zalabí; Válor;
Vegas del Genil; Vélez de Benaudalla; Ventas de Huelma; Villamena; Villanueva de las Torres;
Villanueva Mesía; Víznar; Zafarraya; Zagra; Zújar;
Belicena; Purchil; Ambroz; Gabia Grande; Gabia Chica; Híjar; Hijar; Pradollano; Sierra Nevada;
La Herradura; Castell de Ferro; Calahonda; Carchuna; Torrenueva; La Mamola; Melegís; Restábal;
Pinos del Valle; Las Vegas del Genil; Santa Adela; Fornes; Ventorros de San José; Huétor;
Alpujarra Granadina; Vega de Granada; Costa Tropical; Valle de Lecrín; Altiplano de Granada;
Area metropolitana de Granada
"""


def municipios() -> list[str]:
    return [m.strip() for m in MUNICIPIOS.replace("\n", " ").split(";") if m.strip()]


# Núcleos y formas alternativas con que las webs escriben cada municipio de la zona.
# Se usan para el filtro de zona cerrada (criteria.zona en config.yaml).
ALIAS_ZONA = {
    "Las Gabias": ["Gabias", "Gabias (Las)", "Gabia Grande", "Gabia Chica", "Hijar", "Híjar"],
    "La Zubia": ["Zubia", "Zubia (La)", "Cumbres Verdes"],
    "Vegas del Genil": ["Belicena", "Purchil", "Ambroz", "Las Vegas del Genil"],
    "Churriana de la Vega": ["Churriana"],
    "Cúllar Vega": ["Cullar-Vega"],
    "Huétor Vega": ["Huetor-Vega"],
    "Alhendín": ["El Margen"],
    "Otura": ["Viña del Rey"],
    "Monachil": ["Barrio de Monachil"],
    "Albolote": ["El Chaparral", "Cubillas"],
    "Maracena": [],
}


def variantes_zona(nombres: list[str]) -> list[str]:
    """Nombres + alias, sin repetir."""
    out: list[str] = []
    for n in nombres:
        for v in [n, *ALIAS_ZONA.get(n, [])]:
            if v not in out:
                out.append(v)
    return out