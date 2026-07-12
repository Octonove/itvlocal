"""Tests de logica pura de ITVLocal (evaluadores, scoring y certificado).
Ejecutar:  python -m pytest tests/ -q   (desde la carpeta ITVLocal)"""

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from itvlocal import checks, report, scoring  # noqa: E402
from itvlocal.checks import GRAVE, LEVE, MUY_GRAVE, NO_VERIFICADO, OK  # noqa: E402


# ------------------------------------------------------------- evaluadores
def test_evaluar_espacio_umbrales():
    assert checks.evaluar_espacio(500, 300).estado == OK
    assert checks.evaluar_espacio(500, 80).estado == LEVE       # 16%
    assert checks.evaluar_espacio(500, 40).estado == GRAVE      # 8%
    assert checks.evaluar_espacio(500, 10).estado == MUY_GRAVE  # 2%
    assert checks.evaluar_espacio(0, 0).estado == MUY_GRAVE     # sin division por cero


def test_evaluar_espacio_discos_grandes_no_castiga():
    # 168 GB libres en 2 TB = 9%: en porcentaje seria GRAVE, pero es espacio de
    # sobra -> el suelo absoluto en GB manda (hallazgo de la revision).
    assert checks.evaluar_espacio(2000, 168).estado == OK
    assert checks.evaluar_espacio(2000, 300).estado == OK
    assert checks.evaluar_espacio(2000, 90).estado == LEVE      # 4.5% pero 90 GB


def test_evaluar_salud_disco():
    assert checks.evaluar_salud_disco(["OK", "OK"]).estado == OK
    assert checks.evaluar_salud_disco(["OK", "Pred Fail"]).estado == MUY_GRAVE
    assert checks.evaluar_salud_disco([]).estado == NO_VERIFICADO
    # 'Unknown' (lector USB) NO debe disparar una NEGATIVA falsa
    assert checks.evaluar_salud_disco(["OK", "Unknown"]).estado == OK
    assert checks.evaluar_salud_disco(["Unknown"]).estado == NO_VERIFICADO


def test_evaluar_memoria():
    assert checks.evaluar_memoria(16, 40).estado == OK
    assert checks.evaluar_memoria(16, 95).estado == LEVE
    assert checks.evaluar_memoria(6, 40).estado == LEVE
    assert checks.evaluar_memoria(2, 40).estado == GRAVE
    # ullTotalPhys reporta menos que lo instalado: 8 GB reales ~ 7.9 -> OK
    assert checks.evaluar_memoria(7.9, 40).estado == OK
    assert checks.evaluar_memoria(3.9, 40).estado == LEVE


def test_evaluar_parches():
    assert checks.evaluar_parches(10).estado == OK
    assert checks.evaluar_parches(40).estado == LEVE
    assert checks.evaluar_parches(90).estado == GRAVE
    assert checks.evaluar_parches(None).estado == NO_VERIFICADO


def test_evaluar_antivirus():
    assert checks.evaluar_antivirus(["Defender"], False, True).estado == OK
    assert checks.evaluar_antivirus(["Defender"], True, True).estado == LEVE
    assert checks.evaluar_antivirus([], False, True).estado == MUY_GRAVE
    assert checks.evaluar_antivirus([], False, False).estado == NO_VERIFICADO


def test_evaluar_firewall():
    assert checks.evaluar_firewall([], True).estado == OK
    assert checks.evaluar_firewall(["privado"], True).estado == GRAVE
    assert checks.evaluar_firewall([], False).estado == NO_VERIFICADO


def test_evaluar_arranque():
    assert checks.evaluar_arranque(3).estado == OK
    assert checks.evaluar_arranque(9).estado == LEVE
    assert checks.evaluar_arranque(20).estado == GRAVE
    assert checks.evaluar_arranque(None).estado == NO_VERIFICADO


def test_evaluar_uptime_y_reinicio():
    assert checks.evaluar_uptime(2).estado == OK
    assert checks.evaluar_uptime(15).estado == LEVE
    assert checks.evaluar_uptime(45).estado == GRAVE
    assert checks.evaluar_reinicio(True).estado == LEVE
    assert checks.evaluar_reinicio(False).estado == OK


def test_evaluar_backup_y_windows():
    assert checks.evaluar_backup(True, False).estado == OK
    assert checks.evaluar_backup(False, True).estado == OK
    assert checks.evaluar_backup(False, False).estado == GRAVE
    assert checks.evaluar_windows_version(11, False).estado == OK
    assert checks.evaluar_windows_version(10, True).estado == GRAVE


# ----------------------------------------------------------------- scoring
def _p(estado):
    return checks.Punto("x", "X", estado=estado, detalle="d", consejo="c")


def test_veredicto_favorable():
    v = scoring.calcular([_p(OK), _p(OK), _p(NO_VERIFICADO)], hoy=date(2026, 1, 1))
    assert v.resultado == scoring.FAVORABLE
    assert v.nota == 10.0
    assert v.proxima == date(2026, 7, 2)          # +182 dias


def test_veredicto_desfavorable_y_negativa():
    v = scoring.calcular([_p(OK), _p(GRAVE), _p(LEVE)], hoy=date(2026, 1, 1))
    assert v.resultado == scoring.DESFAVORABLE and v.nota == 8.0
    v2 = scoring.calcular([_p(MUY_GRAVE), _p(GRAVE)], hoy=date(2026, 1, 1))
    assert v2.resultado == scoring.NEGATIVA and v2.nota == 5.5
    assert v2.proxima == date(2026, 1, 16)         # +15 dias


def test_nota_no_baja_de_cero():
    v = scoring.calcular([_p(MUY_GRAVE)] * 5, hoy=date(2026, 1, 1))
    assert v.nota == 0.0


def test_plan_de_accion_ordena_por_gravedad():
    plan = scoring.plan_de_accion([_p(LEVE), _p(MUY_GRAVE), _p(OK), _p(GRAVE)])
    assert [p.estado for p in plan] == [MUY_GRAVE, GRAVE, LEVE]


# ------------------------------------------------------------- certificado
def test_certificado_pdf(tmp_path):
    import fitz
    puntos = [checks.evaluar_espacio(500, 300),
              checks.evaluar_antivirus([], False, True),
              checks.evaluar_uptime(45),
              checks.evaluar_backup(False, False)]
    v = scoring.calcular(puntos, hoy=date(2026, 7, 12))
    out = str(tmp_path / "cert.pdf")
    report.exportar_certificado(puntos, v, out, equipo="Bar Paco",
                                fecha=date(2026, 7, 12))
    doc = fitz.open(out)
    text = "\n".join(doc[p].get_text("text") for p in range(doc.page_count))
    doc.close()
    assert "NEGATIVA" in text                     # hay un muy grave (antivirus)
    assert "Bar Paco" in text
    assert "Plan de accion" in text
    assert "antivirus" in text.lower()


def test_certificado_sin_puntos_lanza(tmp_path):
    v = scoring.calcular([_p(OK)])
    with pytest.raises(report.ReportError):
        report.exportar_certificado([], v, str(tmp_path / "x.pdf"))


def test_certificado_escapa_html(tmp_path):
    import fitz
    p = checks.Punto("x", "<script>alert(1)</script>", estado=GRAVE,
                     valor="<b>v</b>", detalle="d<i>", consejo="c&c")
    v = scoring.calcular([p], hoy=date(2026, 7, 12))
    out = str(tmp_path / "esc.pdf")
    report.exportar_certificado([p], v, out, equipo="<Equipo> & Co")
    doc = fitz.open(out)
    text = doc[0].get_text("text")
    doc.close()
    assert "<script>" in text          # aparece como TEXTO literal, no ejecutado/omitido
    assert "& Co" in text
