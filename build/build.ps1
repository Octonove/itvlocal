# Construye el ejecutable de ITVLocal con PyInstaller (onedir).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = Join-Path $root "..\CapturaPro\.venv\Scripts\python.exe" }
if (-not (Test-Path $py)) { $py = "python" }
Write-Host "Python: $py" -ForegroundColor DarkGray

# Pre-check: el Python elegido debe resolver las dependencias reales; sin esto,
# un fallback al python del sistema produce un exe roto sin error de build.
& $py -c "import octonove_core, fitz" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: ese Python no importa octonove_core/fitz. Usa el venv de la suite (CapturaPro\.venv con octonove_shared.pth) o instala pymupdf." -ForegroundColor Red
    exit 1
}

Write-Host "== Generando icono ==" -ForegroundColor Cyan
& $py (Join-Path $PSScriptRoot "gen_icon.py")
$icon = Join-Path $PSScriptRoot "icon.ico"
if (Test-Path $icon) { $env:APP_ICON = $icon } else { $env:APP_ICON = "" }

Write-Host "== Compilando con PyInstaller ==" -ForegroundColor Cyan
Push-Location $root
& $py -m PyInstaller --noconfirm --clean (Join-Path $PSScriptRoot "ITVLocal.spec")
$code = $LASTEXITCODE
Pop-Location

if ($code -eq 0) {
    Write-Host "`n== LISTO ==" -ForegroundColor Green
    Write-Host "Ejecutable: $(Join-Path $root 'dist\ITVLocal\ITVLocal.exe')"
} else {
    Write-Host "`nLa compilacion fallo (codigo $code)." -ForegroundColor Red
    exit $code
}
