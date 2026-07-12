"""Clasificacion tipo ITV: de la lista de puntos al veredicto, la nota y la
fecha de proxima inspeccion. Logica 100% pura (testeable sin Windows)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .checks import GRAVE, LEVE, MUY_GRAVE, NO_VERIFICADO, OK, Punto

FAVORABLE, DESFAVORABLE, NEGATIVA = "FAVORABLE", "DESFAVORABLE", "NEGATIVA"

_TEXTO = {
    FAVORABLE: "El equipo esta en buen estado. Proxima inspeccion en 6 meses.",
    DESFAVORABLE: ("Hay defectos graves que conviene corregir pronto. "
                   "Repite la inspeccion en 1 mes tras aplicar el plan de accion."),
    NEGATIVA: ("Hay defectos MUY graves: el equipo esta en riesgo real. "
               "Aplica el plan de accion cuanto antes y repite la inspeccion."),
}


@dataclass
class Veredicto:
    resultado: str          # FAVORABLE / DESFAVORABLE / NEGATIVA
    nota: float             # 0..10
    n_leves: int
    n_graves: int
    n_muy_graves: int
    n_no_verificados: int
    texto: str
    proxima: date           # fecha recomendada de proxima inspeccion


def calcular(puntos: list[Punto], hoy: date | None = None) -> Veredicto:
    hoy = hoy or date.today()
    leves = sum(1 for p in puntos if p.estado == LEVE)
    graves = sum(1 for p in puntos if p.estado == GRAVE)
    muy = sum(1 for p in puntos if p.estado == MUY_GRAVE)
    nv = sum(1 for p in puntos if p.estado == NO_VERIFICADO)

    if muy:
        resultado, delta = NEGATIVA, timedelta(days=15)
    elif graves:
        resultado, delta = DESFAVORABLE, timedelta(days=30)
    else:
        resultado, delta = FAVORABLE, timedelta(days=182)

    nota = 10.0 - 0.5 * leves - 1.5 * graves - 3.0 * muy
    nota = max(0.0, min(10.0, round(nota, 1)))
    texto = _TEXTO[resultado]
    # Honestidad: un FAVORABLE con media inspeccion sin comprobar no es un 10.
    if nv >= 2:
        texto += (f" ATENCION: {nv} puntos no se pudieron comprobar; "
                  "el resultado es parcial.")
    return Veredicto(resultado, nota, leves, graves, muy, nv, texto, hoy + delta)


def plan_de_accion(puntos: list[Punto]) -> list[Punto]:
    """Puntos con defecto, ordenados de mas a menos grave (para el plan)."""
    orden = {MUY_GRAVE: 0, GRAVE: 1, LEVE: 2}
    return sorted((p for p in puntos if p.estado in orden),
                  key=lambda p: orden[p.estado])
