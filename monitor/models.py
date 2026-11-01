from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Listing:
    """Anuncio normalizado. Todas las fuentes devuelven objetos de este tipo."""

    source: str                      # id de la fuente (p.ej. "inmofuturo")
    id: str                          # id del anuncio dentro de la fuente
    url: str
    title: str = ""
    municipality: str = ""           # municipio o zona tal y como lo da la web
    ptype: str = ""                  # tipo de inmueble (piso, casa, chalet...)
    price: Optional[int] = None      # euros
    rooms: Optional[int] = None      # habitaciones / dormitorios
    m2: Optional[int] = None
    photo: Optional[str] = None
    sort_key: str = ""               # para ordenar por "más reciente" (fecha ISO o id con ceros a la izquierda)
    province_ok: Optional[bool] = None  # True/False si la fuente lo sabe; None = comprobar por municipio
    is_sale: bool = True             # False si es alquiler / traspaso
    needs_enrich: bool = False       # True si falta info que se completa abriendo la ficha
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, str]:
        return (self.source, self.id)


def id_sort_key(value) -> str:
    """Convierte un id numérico en una clave ordenable como texto."""
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return digits.zfill(20) if digits else ""
