"""Motor de inspeccion de ITVLocal.

Cada punto de inspeccion tiene dos mitades:
  - una MEDICION best-effort (lee el sistema con stdlib/ctypes/PowerShell; si
    falla, el punto queda "no_verificado" y JAMAS rompe la inspeccion), y
  - un EVALUADOR PURO (recibe numeros, devuelve estado+textos) que es lo que
    cubren los tests.

Filosofia ITV: solo se INSPECCIONA y documenta. Nunca se arregla, borra ni
"optimiza" nada. Ningun dato sale del equipo. No requiere administrador.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Estados posibles de un punto, de mejor a peor (mismo lenguaje que la ITV).
OK, LEVE, GRAVE, MUY_GRAVE, NO_VERIFICADO = "ok", "leve", "grave", "muy_grave", "no_verificado"

ETIQUETA = {OK: "Correcto", LEVE: "Defecto leve", GRAVE: "Defecto grave",
            MUY_GRAVE: "Defecto muy grave", NO_VERIFICADO: "No verificado"}


@dataclass
class Punto:
    clave: str
    nombre: str
    estado: str = NO_VERIFICADO
    valor: str = ""       # dato corto para la tabla ("38 GB libres (12%)")
    detalle: str = ""     # explicacion en llano
    consejo: str = ""     # que hacer (vacio si estado ok)


def _powershell_exe() -> str:
    """Ruta absoluta de powershell.exe (endurecimiento: no depender del PATH)."""
    root = os.environ.get("SystemRoot", r"C:\Windows")
    p = Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return str(p) if p.is_file() else "powershell"


def _pwsh(cmd: str, timeout: float = 20.0) -> str:
    """Ejecuta un comando PowerShell OCULTO y devuelve stdout ('' si falla).
    Solo LECTURAS (Get-*): ITVLocal jamas modifica el sistema."""
    try:
        flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        p = subprocess.run(
            [_powershell_exe(), "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True, timeout=timeout, creationflags=flags)
        if p.returncode != 0:
            return ""
        # PowerShell 5.1 puede emitir en la pagina de codigos OEM (cp850) en vez
        # de UTF-8: probamos UTF-8 estricto y caemos a OEM (evita mojibake).
        try:
            return p.stdout.decode("utf-8")
        except UnicodeDecodeError:
            return p.stdout.decode("oem", "replace")
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("PowerShell fallo (%s): %s", cmd[:40], exc)
        return ""


# ------------------------------------------------------------- evaluadores puros
def evaluar_espacio(total_gb: float, libre_gb: float) -> Punto:
    pct = (libre_gb / total_gb * 100) if total_gb > 0 else 0
    p = Punto("disco_espacio", "Espacio libre en el disco",
              valor=f"{libre_gb:.0f} GB libres de {total_gb:.0f} GB ({pct:.0f}%)")
    # En discos grandes el porcentaje engana: 150 GB libres son de sobra aunque
    # sean el 8% de un disco de 2 TB. El porcentaje se combina con suelos en GB.
    if libre_gb >= 150:
        p.estado, p.detalle = OK, "Hay espacio de sobra para que Windows trabaje comodo."
        return p
    if pct < 5 and libre_gb < 25:
        p.estado, p.detalle = MUY_GRAVE, ("El disco esta practicamente lleno. Windows puede "
                                          "volverse inestable y dejar de actualizar.")
        p.consejo = "Libera espacio urgentemente: mueve fotos/videos a un disco externo y vacia la papelera."
    elif pct < 10 and libre_gb < 60:
        p.estado, p.detalle = GRAVE, "Queda muy poco espacio libre; el equipo ira cada vez mas lento."
        p.consejo = "Libera espacio: desinstala programas que no uses y mueve archivos grandes a otro disco."
    elif pct < 20:
        p.estado, p.detalle = LEVE, "El espacio libre empieza a escasear."
        p.consejo = "Revisa Descargas y la papelera; valora mover archivos grandes a otro disco."
    else:
        p.estado, p.detalle = OK, "Hay espacio de sobra para que Windows trabaje comodo."
    return p


def evaluar_salud_disco(statuses: list[str]) -> Punto:
    p = Punto("disco_salud", "Salud del disco duro/SSD",
              valor=", ".join(statuses) if statuses else "sin datos")
    if not statuses:
        p.estado = NO_VERIFICADO
        p.detalle = "No se pudo leer el estado de los discos."
        return p
    # Solo los estados NEGATIVOS documentados son alarma: 'Unknown'/'Starting'
    # (tipicos de lectores USB o discos recien conectados) no deben convertir el
    # certificado en NEGATIVA por un falso positivo.
    malos = [s for s in statuses
             if s.strip().lower() in ("pred fail", "predfail", "error", "degraded", "fail")]
    ok_conocidos = [s for s in statuses if s.strip().lower() == "ok"]
    if malos:
        p.estado = MUY_GRAVE
        p.detalle = ("Windows informa de un posible fallo inminente del disco "
                     f"({', '.join(malos)}). Riesgo real de perder los datos.")
        p.consejo = "HAZ COPIA DE SEGURIDAD HOY y lleva el equipo a un tecnico para cambiar el disco."
    elif ok_conocidos:
        p.estado, p.detalle = OK, "Los discos no reportan fallos."
    else:
        p.estado = NO_VERIFICADO
        p.detalle = "El estado que reporta Windows no es concluyente."
    return p


def evaluar_memoria(total_gb: float, carga_pct: float) -> Punto:
    p = Punto("memoria", "Memoria RAM",
              valor=f"{total_gb:.0f} GB instalados · {carga_pct:.0f}% en uso")
    # ullTotalPhys reporta la RAM UTILIZABLE (el firmware reserva parte): un
    # equipo de 8 GB reporta ~7,9. Umbral con tolerancia para no marcar en falso
    # justo la configuracion mas comun.
    if total_gb < 3.5:
        p.estado = GRAVE
        p.detalle = "Con menos de 4 GB de RAM, Windows moderno va a rastras."
        p.consejo = "Amplia la memoria (es la mejora mas barata) o valora renovar el equipo."
    elif total_gb < 7.5:
        p.estado = LEVE
        p.detalle = "8 GB es el minimo comodo hoy; con menos, el equipo se ahoga al abrir varias cosas."
        p.consejo = "Si notas lentitud con varias ventanas abiertas, ampliar la RAM lo soluciona."
    elif carga_pct > 92:
        p.estado = LEVE
        p.detalle = "La memoria esta casi al limite ahora mismo."
        p.consejo = "Cierra programas que no uses; si pasa a diario, valora ampliar la RAM."
    else:
        p.estado, p.detalle = OK, "Memoria suficiente y con margen."
    return p


def evaluar_parches(dias_ultimo: int | None) -> Punto:
    p = Punto("windows_update", "Actualizaciones de Windows",
              valor="sin datos" if dias_ultimo is None else f"ultimo parche hace {dias_ultimo} dias")
    if dias_ultimo is None:
        p.estado = NO_VERIFICADO
        p.detalle = "No se pudo determinar cuando se actualizo Windows por ultima vez."
        return p
    if dias_ultimo > 60:
        p.estado = GRAVE
        p.detalle = ("Windows lleva mas de dos meses sin parches: agujeros de seguridad "
                     "conocidos siguen abiertos.")
        p.consejo = "Abre Configuracion > Windows Update y deja que instale todo (puede tardar)."
    elif dias_ultimo > 35:
        p.estado = LEVE
        p.detalle = "Hace mas de un mes del ultimo parche."
        p.consejo = "Pasa por Configuracion > Windows Update y busca actualizaciones."
    else:
        p.estado, p.detalle = OK, "Windows esta recibiendo sus parches con normalidad."
    return p


def evaluar_antivirus(nombres_activos: list[str], alguno_desactualizado: bool,
                      consultado: bool) -> Punto:
    p = Punto("antivirus", "Antivirus",
              valor=", ".join(nombres_activos) if nombres_activos else "ninguno activo")
    if not consultado:
        p.estado = NO_VERIFICADO
        p.detalle = "No se pudo consultar el estado del antivirus."
        return p
    if not nombres_activos:
        p.estado = MUY_GRAVE
        p.detalle = "No hay ningun antivirus activo protegiendo el equipo."
        p.consejo = ("Activa Windows Defender (Seguridad de Windows > Proteccion antivirus): "
                     "viene gratis con Windows y es suficiente.")
    elif alguno_desactualizado:
        p.estado = LEVE
        p.detalle = "Hay antivirus activo pero sus definiciones no estan al dia."
        p.consejo = "Abre tu antivirus y fuerza una actualizacion de definiciones."
    else:
        p.estado, p.detalle = OK, "Antivirus activo y al dia."
    return p


def evaluar_firewall(perfiles_off: list[str], consultado: bool) -> Punto:
    p = Punto("firewall", "Cortafuegos (firewall)",
              valor="activado" if (consultado and not perfiles_off) else
              (", ".join(perfiles_off) + " desactivado(s)" if perfiles_off else "sin datos"))
    if not consultado:
        p.estado = NO_VERIFICADO
        p.detalle = "No se pudo consultar el estado del cortafuegos."
        return p
    if perfiles_off:
        p.estado = GRAVE
        p.detalle = f"El cortafuegos esta desactivado en: {', '.join(perfiles_off)}."
        p.consejo = "Activalo en Seguridad de Windows > Firewall y proteccion de red."
    else:
        p.estado, p.detalle = OK, "El cortafuegos esta activo en todos los perfiles."
    return p


def evaluar_arranque(n_programas: int | None) -> Punto:
    p = Punto("arranque", "Programas que arrancan con Windows",
              valor="sin datos" if n_programas is None else f"{n_programas} programas")
    if n_programas is None:
        p.estado = NO_VERIFICADO
        p.detalle = "No se pudo contar los programas de arranque."
        return p
    if n_programas > 12:
        p.estado = GRAVE
        p.detalle = (f"{n_programas} programas arrancan solos con Windows: el encendido "
                     "es lento y el equipo va cargado desde el minuto uno.")
        p.consejo = "Administrador de tareas > Inicio: deshabilita los que no necesites al arrancar."
    elif n_programas > 7:
        p.estado = LEVE
        p.detalle = f"{n_programas} programas arrancan con Windows; alguno seguramente sobra."
        p.consejo = "Revisa Administrador de tareas > Inicio y deshabilita lo que no uses a diario."
    else:
        p.estado, p.detalle = OK, "Pocos programas en el arranque: encendido agil."
    return p


def evaluar_reinicio(pendiente: bool) -> Punto:
    p = Punto("reinicio", "Reinicio pendiente",
              valor="pendiente" if pendiente else "no")
    if pendiente:
        p.estado = LEVE
        p.detalle = "Windows tiene cambios a medias esperando un reinicio."
        p.consejo = "Reinicia el equipo cuando te venga bien (guarda antes tu trabajo)."
    else:
        p.estado, p.detalle = OK, "No hay reinicios pendientes."
    return p


def evaluar_uptime(dias: float) -> Punto:
    p = Punto("uptime", "Dias sin reiniciar", valor=f"{dias:.0f} dias")
    if dias > 30:
        p.estado = GRAVE
        p.detalle = (f"El equipo lleva {dias:.0f} dias sin reiniciarse de verdad: memoria "
                     "fragmentada, parches sin aplicar y errores acumulados.")
        p.consejo = "Reinicia (no 'apagar': con inicio rapido, apagar no reinicia de verdad)."
    elif dias > 10:
        p.estado = LEVE
        p.detalle = f"{dias:.0f} dias sin reiniciar; conviene un reinicio de vez en cuando."
        p.consejo = "Reinicia el equipo esta semana."
    else:
        p.estado, p.detalle = OK, "El equipo se reinicia con regularidad."
    return p


def evaluar_backup(file_history: bool, onedrive_kfm: bool) -> Punto:
    detectado = file_history or onedrive_kfm
    fuente = ("Historial de archivos" if file_history else
              "OneDrive (carpetas protegidas)" if onedrive_kfm else "ninguna")
    p = Punto("backup", "Copia de seguridad automatica", valor=fuente)
    if detectado:
        p.estado = OK
        p.detalle = f"Se detecto una copia de seguridad automatica ({fuente})."
    else:
        p.estado = GRAVE
        p.detalle = ("No se detecto ninguna copia de seguridad automatica conocida "
                     "(Historial de archivos u OneDrive). Si el disco muere, los "
                     "documentos se pierden. (Si usas otro sistema de copias, ignora este punto.)")
        p.consejo = ("Activa OneDrive con proteccion de carpetas o el Historial de archivos "
                     "con un disco externo. Es la diferencia entre un susto y una catastrofe.")
    return p


def evaluar_windows_version(major: int, es_win10: bool) -> Punto:
    p = Punto("windows", "Version de Windows", valor=f"Windows {major}")
    if es_win10:
        p.estado = GRAVE
        p.detalle = ("Windows 10 dejo de recibir soporte y parches de seguridad en "
                     "octubre de 2025: cada mes que pasa es mas vulnerable.")
        p.consejo = "Planifica el paso a Windows 11 (o a un equipo nuevo si el actual no lo admite)."
    else:
        p.estado, p.detalle = OK, "Version de Windows con soporte."
    return p


# ------------------------------------------------------------------- mediciones
def medir_espacio() -> Punto:
    try:
        import shutil
        u = shutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\")
        return evaluar_espacio(u.total / 1024**3, u.free / 1024**3)
    except OSError:
        return Punto("disco_espacio", "Espacio libre en el disco",
                     detalle="No se pudo leer el disco.")


def medir_salud_disco() -> Punto:
    out = _pwsh("(Get-CimInstance Win32_DiskDrive).Status")
    statuses = [ln.strip() for ln in out.splitlines() if ln.strip()]
    return evaluar_salud_disco(statuses)


def medir_memoria() -> Punto:
    try:
        import ctypes

        class _MEM(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        m = _MEM()
        m.dwLength = ctypes.sizeof(_MEM)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return evaluar_memoria(m.ullTotalPhys / 1024**3, float(m.dwMemoryLoad))
    except Exception:  # noqa: BLE001
        return Punto("memoria", "Memoria RAM", detalle="No se pudo leer la memoria.")


def medir_parches() -> Punto:
    # Get-HotFix es rapido y no requiere admin. Cultura INVARIANTE: sin ella,
    # ToString usa el calendario regional (p.ej. budista +543 anos) y el check
    # daria falsos resultados en Windows con esas configuraciones.
    out = _pwsh("(Get-HotFix | Sort-Object InstalledOn -Descending | "
                "Select-Object -First 1).InstalledOn.ToString('yyyy-MM-dd', "
                "[System.Globalization.CultureInfo]::InvariantCulture)")
    dias = None
    fecha = out.strip().splitlines()[0].strip() if out.strip() else ""
    if fecha:
        try:
            from datetime import date
            y, mo, d = (int(x) for x in fecha.split("-"))
            dias = (date.today() - date(y, mo, d)).days
            if dias < 0:
                dias = None       # fecha en el futuro: reloj o calendario raros
        except ValueError:
            dias = None
    return evaluar_parches(dias)


def medir_antivirus() -> Punto:
    out = _pwsh("Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntiVirusProduct | "
                "ForEach-Object { $_.displayName + '|' + $_.productState }")
    if not out.strip():
        return evaluar_antivirus([], False, consultado=False)
    activos, desactualizado = [], False
    for ln in out.splitlines():
        if "|" not in ln:
            continue
        nombre, _, estado = ln.strip().rpartition("|")
        try:
            st = int(estado)
        except ValueError:
            continue
        # productState: byte medio 0x10 = activo; byte bajo 0x10 = definiciones viejas
        if (st >> 12) & 0xF == 1:
            activos.append(nombre)
            if (st & 0xFF) == 0x10:
                desactualizado = True
    return evaluar_antivirus(activos, desactualizado, consultado=True)


def _nombre_perfil_firewall(linea: str) -> str:
    """Nombre corto del perfil a partir de la cabecera de netsh (es/en)."""
    low = linea.lower()
    for clave, nombre in (("dominio", "dominio"), ("domain", "dominio"),
                          ("privado", "privado"), ("private", "privado"),
                          ("public", "publico"), ("públic", "publico"), ("publico", "publico")):
        if clave in low:
            return nombre
    return "un perfil"


def medir_firewall() -> Punto:
    root = os.environ.get("SystemRoot", r"C:\Windows")
    netsh = str(Path(root) / "System32" / "netsh.exe")
    out = _pwsh(f"& '{netsh}' advfirewall show allprofiles state")
    if not out.strip():
        return evaluar_firewall([], consultado=False)
    perfiles_off: list[str] = []
    actual = ""
    for ln in out.splitlines():
        low = ln.strip().lower()
        if "perfil" in low or "profile" in low:
            actual = _nombre_perfil_firewall(ln)
        # 'Estado ... DESACTIVAR/OFF' segun idioma
        if low.startswith(("estado", "state")) and ("desactiv" in low or low.endswith("off")):
            perfiles_off.append(actual or "un perfil")
    return evaluar_firewall(perfiles_off, consultado=True)


def _deshabilitados_startup(winreg, hive, approved_path: str) -> set[str]:
    """Nombres marcados como DESHABILITADOS en StartupApproved (el Administrador
    de tareas no borra el valor de Run: lo marca aqui con el bit 0 del primer
    byte a 1). Sin este filtro se contaban programas que YA no arrancan."""
    des: set[str] = set()
    try:
        with winreg.OpenKey(hive, approved_path) as k:
            n = winreg.QueryInfoKey(k)[1]
            for i in range(n):
                nombre, datos, _t = winreg.EnumValue(k, i)
                if isinstance(datos, bytes) and datos and (datos[0] & 0x1):
                    des.add(nombre.lower())
    except OSError:
        pass
    return des


def medir_arranque() -> Punto:
    total = 0
    try:
        import winreg
        base_app = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved"
        for hive, run_path, app_path in (
                (winreg.HKEY_CURRENT_USER,
                 r"Software\Microsoft\Windows\CurrentVersion\Run", base_app + r"\Run"),
                (winreg.HKEY_LOCAL_MACHINE,
                 r"Software\Microsoft\Windows\CurrentVersion\Run", base_app + r"\Run"),
                (winreg.HKEY_LOCAL_MACHINE,
                 r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run",
                 base_app + r"\Run32")):
            deshab = _deshabilitados_startup(winreg, hive, app_path)
            try:
                with winreg.OpenKey(hive, run_path) as k:
                    n = winreg.QueryInfoKey(k)[1]
                    for i in range(n):
                        nombre, _d, _t = winreg.EnumValue(k, i)
                        if nombre.lower() not in deshab:
                            total += 1
            except OSError:
                continue
        # carpetas de Inicio (del usuario y comun), filtrando las deshabilitadas
        deshab_carpeta = _deshabilitados_startup(
            winreg, winreg.HKEY_CURRENT_USER, base_app + r"\StartupFolder")
        carpetas = [Path(os.environ.get("APPDATA", "")) /
                    r"Microsoft\Windows\Start Menu\Programs\Startup",
                    Path(os.environ.get("ProgramData", r"C:\ProgramData")) /
                    r"Microsoft\Windows\Start Menu\Programs\StartUp"]
        for carpeta in carpetas:
            if carpeta.is_dir():
                for f in carpeta.iterdir():
                    if f.suffix.lower() in (".lnk", ".exe", ".bat") and \
                            f.name.lower() not in deshab_carpeta:
                        total += 1
        return evaluar_arranque(total)
    except Exception:  # noqa: BLE001
        return evaluar_arranque(None)


def medir_reinicio() -> Punto:
    pendiente = False
    try:
        import winreg
        for path in (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending",
                     r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired"):
            try:
                winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path).Close()
                pendiente = True
                break
            except OSError:
                continue
    except Exception:  # noqa: BLE001
        pass
    return evaluar_reinicio(pendiente)


def medir_uptime() -> Punto:
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        # OBLIGATORIO: sin restype, ctypes trunca el ULONGLONG a 32 bits con
        # signo y a partir de ~24,8 dias el uptime sale NEGATIVO (falso OK
        # justo en los equipos que nunca se reinician).
        k32.GetTickCount64.restype = ctypes.c_ulonglong
        ms = int(k32.GetTickCount64())
        if ms < 0:
            return Punto("uptime", "Dias sin reiniciar", detalle="Lectura no valida.")
        return evaluar_uptime(ms / 86_400_000)
    except Exception:  # noqa: BLE001
        return Punto("uptime", "Dias sin reiniciar", detalle="No se pudo leer.")


def medir_backup() -> Punto:
    # La clave FileHistory EXISTE por defecto en Windows aunque nadie haya
    # configurado nada: exigir evidencia real (valor ProtectedUpToTime o el
    # Config1.xml del Historial). Si no, dariamos un falso "tienes copia" —
    # el falso positivo mas peligroso posible en esta app.
    file_history = False
    try:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\FileHistory") as k:
                winreg.QueryValueEx(k, "ProtectedUpToTime")
                file_history = True
        except OSError:
            pass
    except Exception:  # noqa: BLE001
        pass
    if not file_history:
        cfg = (Path(os.environ.get("LOCALAPPDATA", "")) /
               r"Microsoft\Windows\FileHistory\Configuration\Config1.xml")
        try:
            file_history = cfg.is_file()
        except OSError:
            pass
    # OneDrive KFM: Documentos dentro de una carpeta OneDrive
    onedrive_kfm = False
    try:
        docs = _docs_dir()
        onedrive_kfm = "onedrive" in str(docs).lower()
    except Exception:  # noqa: BLE001
        pass
    return evaluar_backup(file_history, onedrive_kfm)


def _docs_dir() -> Path:
    """Carpeta Documentos REAL (respetando redirecciones de OneDrive), via registro."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
            v, _ = winreg.QueryValueEx(k, "Personal")
            return Path(os.path.expandvars(v))
    except OSError:
        return Path.home() / "Documents"


def medir_windows_version() -> Punto:
    try:
        import sys
        build = sys.getwindowsversion().build
        # build >= 22000 -> Windows 11
        return evaluar_windows_version(11 if build >= 22000 else 10, es_win10=build < 22000)
    except Exception:  # noqa: BLE001
        return Punto("windows", "Version de Windows", detalle="No se pudo determinar.")


# Lista ordenada de mediciones: (funcion, es_lenta). Las lentas van al final para
# que la UI muestre resultados desde el primer segundo.
MEDICIONES = [
    (medir_espacio, False),
    (medir_memoria, False),
    (medir_uptime, False),
    (medir_reinicio, False),
    (medir_arranque, False),
    (medir_backup, False),
    (medir_windows_version, False),
    (medir_firewall, True),
    (medir_salud_disco, True),
    (medir_antivirus, True),
    (medir_parches, True),
]


def inspeccionar(on_punto=None) -> list[Punto]:
    """Ejecuta todos los puntos. on_punto(Punto, i, total) se llama al terminar
    cada uno (para pintar la UI en vivo). Cada medicion es best-effort."""
    puntos: list[Punto] = []
    total = len(MEDICIONES)
    for i, (fn, _lenta) in enumerate(MEDICIONES, 1):
        t0 = time.time()
        try:
            p = fn()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Punto %s fallo: %s", fn.__name__, exc)
            p = Punto(fn.__name__, fn.__name__.replace("medir_", "").replace("_", " ").title())
        logger.info("%s -> %s (%.1fs)", p.clave, p.estado, time.time() - t0)
        puntos.append(p)
        if on_punto:
            try:
                on_punto(p, i, total)
            except Exception:  # noqa: BLE001
                pass
    return puntos
