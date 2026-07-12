"""Certificado PDF de la inspeccion (PyMuPDF).

El texto se dibuja con insert_htmlbox midiendo el alto real en una pagina
scratch (leccion de la suite: insert_textbox con altos calculados a mano puede
descartar texto en silencio)."""

from __future__ import annotations

import html
from datetime import date
from pathlib import Path

from .checks import ETIQUETA, GRAVE, LEVE, MUY_GRAVE, NO_VERIFICADO, OK, Punto
from .scoring import DESFAVORABLE, FAVORABLE, NEGATIVA, Veredicto, plan_de_accion

PW, PH, M = 595, 842, 42
TW = PW - 2 * M

NAVY = "#1e3a5f"
TERRA = "#ce6e61"
COLOR = {OK: "#16a34a", LEVE: "#d97706", GRAVE: "#dc2626",
         MUY_GRAVE: "#7f1d1d", NO_VERIFICADO: "#64748b"}
COLOR_RESULTADO = {FAVORABLE: "#16a34a", DESFAVORABLE: "#d97706", NEGATIVA: "#dc2626"}


class ReportError(Exception):
    pass


def _measure(html_str: str, width: float) -> float:
    import fitz
    d = fitz.open()
    try:
        pg = d.new_page(width=width + 80, height=4000)
        spare, _ = pg.insert_htmlbox(fitz.Rect(0, 0, width, 4000), html_str)
        return max(1.0, 4000 - spare)
    finally:
        d.close()


def _rgb(hexcolor: str) -> tuple[float, float, float]:
    c = hexcolor.lstrip("#")
    return int(c[0:2], 16) / 255, int(c[2:4], 16) / 255, int(c[4:6], 16) / 255


def exportar_certificado(puntos: list[Punto], veredicto: Veredicto, out_path: str, *,
                         equipo: str = "", fecha: date | None = None) -> str:
    import fitz
    if not puntos:
        raise ReportError("No hay puntos de inspeccion que certificar.")
    fecha = fecha or date.today()
    doc = fitz.open()
    try:
        page = doc.new_page(width=PW, height=PH)
        y = M

        def put(html_str: str, gap: float = 6.0):
            nonlocal y, page
            h = _measure(html_str, TW)
            if y + h > PH - M:
                page = doc.new_page(width=PW, height=PH)
                y = M
            page.insert_htmlbox(fitz.Rect(M, y, PW - M, min(y + h + 2, PH - M)), html_str)
            y += h + gap

        # --- cabecera tipo certificado ---
        page.draw_rect(fitz.Rect(0, 0, PW, 86), color=_rgb(NAVY), fill=_rgb(NAVY))
        page.insert_htmlbox(fitz.Rect(M, 16, PW - M, 56),
                            '<div style="font-family:sans-serif;font-size:22px;font-weight:bold;'
                            'color:#ffffff">Certificado de Inspeccion Tecnica del PC</div>')
        page.insert_htmlbox(fitz.Rect(M, 52, PW - M, 82),
                            '<div style="font-family:sans-serif;font-size:10px;color:#b7c7da">'
                            'ITVLocal · inspeccion 100% local — solo se inspecciona y documenta, '
                            'nada se modifica ni sale del equipo</div>')
        y = 100

        eq = html.escape(equipo) if equipo.strip() else "Equipo sin nombre"
        put(f'<div style="font-family:sans-serif;font-size:12px;color:#334155">'
            f'<b>Equipo:</b> {eq} &nbsp;·&nbsp; <b>Fecha:</b> {fecha.strftime("%d/%m/%Y")}</div>', 10)

        # --- resultado y nota ---
        rc = COLOR_RESULTADO[veredicto.resultado]
        put(f'<div style="font-family:sans-serif;font-size:26px;font-weight:bold;color:{rc}">'
            f'{veredicto.resultado} &nbsp;·&nbsp; {veredicto.nota:g}/10</div>', 2)
        put(f'<div style="font-family:sans-serif;font-size:11px;color:#334155">'
            f'{html.escape(veredicto.texto)}<br>'
            f'<b>Proxima inspeccion recomendada:</b> {veredicto.proxima.strftime("%d/%m/%Y")}</div>', 10)

        # --- tabla de puntos ---
        put(f'<div style="font-family:sans-serif;font-size:14px;font-weight:bold;color:{NAVY}">'
            f'Puntos inspeccionados</div>', 4)
        filas = []
        for p in puntos:
            c = COLOR[p.estado]
            filas.append(
                f'<tr><td style="padding:4px 6px;white-space:nowrap;color:{c};font-weight:bold">'
                f'&#9679; {ETIQUETA[p.estado]}</td>'
                f'<td style="padding:4px 6px"><b>{html.escape(p.nombre)}</b>'
                f'<span style="color:#64748b"> — {html.escape(p.valor)}</span></td></tr>')
        # La tabla se emite en TROZOS: un bloque mas alto que la pagina se
        # encogeria hasta ser ilegible (insert_htmlbox reescala, no pagina).
        for i in range(0, len(filas), 8):
            put('<table style="font-family:sans-serif;font-size:10px;border-collapse:collapse">'
                + "".join(filas[i:i + 8]) + "</table>", 2)
        y += 10

        # --- plan de accion ---
        plan = plan_de_accion(puntos)
        if plan:
            put(f'<div style="font-family:sans-serif;font-size:14px;font-weight:bold;color:{NAVY}">'
                f'Plan de accion (de mas a menos urgente)</div>', 4)
            for i, p in enumerate(plan, 1):
                c = COLOR[p.estado]
                put(f'<div style="font-family:sans-serif;font-size:10px;color:#334155;'
                    f'line-height:1.45"><b style="color:{c}">{i}. {html.escape(p.nombre)} '
                    f'({ETIQUETA[p.estado].lower()})</b><br>'
                    f'{html.escape(p.detalle)}<br>'
                    f'<b>Que hacer:</b> {html.escape(p.consejo or "—")}</div>', 7)
        elif veredicto.n_no_verificados:
            put(f'<div style="font-family:sans-serif;font-size:11px;color:#64748b">'
                f'Sin defectos en los puntos verificados, pero {veredicto.n_no_verificados} '
                f'punto(s) no se pudieron comprobar: repite la inspeccion o consultalo '
                f'con un tecnico.</div>', 8)
        else:
            put('<div style="font-family:sans-serif;font-size:11px;color:#16a34a">'
                'Sin defectos: no hay plan de accion. ¡Asi da gusto!</div>', 8)

        # --- pie ---
        pie = ('<div style="font-family:sans-serif;font-size:8px;color:#94a3b8">'
               'Generado con ITVLocal (gratis y open source) · simplificaconia.com · '
               'Este informe es orientativo: inspecciona y documenta, no sustituye a un tecnico.</div>')
        ph = _measure(pie, TW)
        if y + ph > PH - 20:
            page = doc.new_page(width=PW, height=PH)
        page.insert_htmlbox(fitz.Rect(M, PH - 20 - ph, PW - M, PH - 16), pie)

        try:
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            doc.save(out_path, garbage=3, deflate=True)
        except Exception as exc:  # noqa: BLE001
            raise ReportError("No se pudo guardar el certificado. Si lo tienes abierto "
                              "en un visor de PDF, cierralo y vuelve a intentarlo.") from exc
    finally:
        doc.close()
    return out_path
