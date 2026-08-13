# ITVLocal

La **ITV de tu ordenador**, 100% local: pasa una inspección de 1-3 minutos (disco, memoria, actualizaciones, antivirus, copias de seguridad…) y obtén un **certificado PDF** con nota, defectos y plan de acción en español llano — como la ITV del coche: favorable, desfavorable o negativa, con fecha de próxima revisión.

> ITVLocal **solo inspecciona y documenta**: jamás borra, "limpia" ni cambia nada de tu equipo. No es un optimizador. Y nada sale de tu PC.

## ⬇️ Descargar (Windows 10/11)

### ➡️ [**Descargar ITVLocal (instalador .exe)**](https://github.com/Octonove/itvlocal/releases/latest/download/ITVLocal-Setup.exe)

Descarga **directa** del instalador, sin registro. También puedes ver la [última versión y notas](https://github.com/Octonove/itvlocal/releases/latest).

> Si Windows muestra *"Windows protegió tu PC"* (es normal en programas nuevos sin firma): pulsa **Más información → Ejecutar de todas formas**. Se instala sin permisos de administrador.

---

## Qué inspecciona

- **Disco**: espacio libre y estado de salud que reporta Windows.
- **Memoria RAM**: cantidad instalada y carga actual.
- **Actualizaciones**: cuánto hace del último parche de Windows y si hay reinicio pendiente.
- **Seguridad**: antivirus activo y al día, cortafuegos por perfil.
- **Arranque**: cuántos programas se lanzan solos con Windows.
- **Copia de seguridad**: si se detecta alguna automática (Historial de archivos u OneDrive).
- **Higiene**: días sin reiniciar y versión de Windows con soporte.

Cada punto se clasifica como en la ITV real — **correcto, defecto leve, grave o muy grave** — y el conjunto da el veredicto (favorable / desfavorable / negativa), la nota 0-10 y la fecha de la próxima inspección. El **certificado PDF** incluye la tabla de puntos con semáforos y el plan de acción ordenado por urgencia: perfecto para enviárselo a tus clientes si eres el informático, o para archivarlo como evidencia de diligencia.

- **Explicar con IA** (opcional, [Ollama](https://ollama.com) gratis en tu PC o una API con tu clave): reescribe el plan "como a tu cuñado". Sin IA, la app es 100% funcional.
- **Recordatorio integrado**: al abrir la app, te avisa si ya toca la siguiente inspección.

## Stack

Python 3 + Tkinter (ttk) · PyMuPDF (certificado PDF) · ctypes/Win32 + PowerShell de solo lectura · Ollama/API opcional.

Depende del paquete compartido de la suite [`octonove-core`](https://github.com/Octonove/octonove-core) (tema, capa IA, config): debe estar en el `sys.path` del entorno (vía `.pth` o copia junto al proyecto).

## Compilar

```powershell
.\build\build.ps1              # ejecutable (PyInstaller onedir)
.\build\build-installer.ps1    # instalador (Inno Setup)
```

## Tests

```powershell
python -m pytest tests/ -q
```

## Licencia

[MIT](LICENSE) — © 2026 Octonove.
