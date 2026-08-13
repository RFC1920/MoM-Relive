param(
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ProjectDir
$Version = (python -c "from version import __version__; print(__version__)").Trim()
if (-not $Version) { throw "Could not read the version" }

$LicenseDir = Join-Path $ProjectDir "dist\licenses"
New-Item -ItemType Directory -Path $LicenseDir -Force | Out-Null
$PythonLicense = (python -c "import pathlib,sys; p=pathlib.Path(sys.base_prefix)/'LICENSE.txt'; print(p if p.is_file() else '')").Trim()
$PyInstallerLicense = (python -c "import importlib.metadata as m; d=m.distribution('pyinstaller'); print(next((d.locate_file(f) for f in d.files if str(f).replace(chr(92),'/').endswith('licenses/COPYING.txt')), ''))").Trim()
$TclTkLicense = (python -c "import pathlib,sys; p=pathlib.Path(sys.base_prefix)/'tcl'/'tk8.6'/'license.terms'; print(p if p.is_file() else '')").Trim()
$RequiredNotices = @(
    @($PythonLicense, (Join-Path $LicenseDir "PYTHON-LICENSE.txt")),
    @($PyInstallerLicense, (Join-Path $LicenseDir "PYINSTALLER-LICENSE.txt")),
    @($TclTkLicense, (Join-Path $LicenseDir "TCL-TK-LICENSE.txt"))
)
foreach ($Notice in $RequiredNotices) {
    if (-not $Notice[0] -or -not (Test-Path -LiteralPath $Notice[0] -PathType Leaf)) {
        throw "A required third-party licence could not be located"
    }
    Copy-Item -LiteralPath $Notice[0] -Destination $Notice[1] -Force
}

if (-not $SkipTests) {
    python -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw "Tests failed" }
}

python -m PyInstaller --noconfirm --clean --onefile --windowed --uac-admin `
    --name MoMRevival mom_revival.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

python -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name MoMClientLauncher client_launcher.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed while building the launcher" }

python -m PyInstaller --noconfirm --clean --onefile --windowed --uac-admin `
    --name MoMServerManager server_manager.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed while building the server manager" }

python -m PyInstaller --noconfirm --clean --onefile --console --uac-admin `
    --name MoMNativeServer native_server.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed while building the native server launcher" }

$Exe = Join-Path $ProjectDir "dist\MoMRevival.exe"
if (-not (Test-Path -LiteralPath $Exe)) { throw "$Exe was not generated" }
$LauncherExe = Join-Path $ProjectDir "dist\MoMClientLauncher.exe"
if (-not (Test-Path -LiteralPath $LauncherExe)) { throw "$LauncherExe was not generated" }
$ManagerExe = Join-Path $ProjectDir "dist\MoMServerManager.exe"
if (-not (Test-Path -LiteralPath $ManagerExe)) { throw "$ManagerExe was not generated" }
$NativeServerExe = Join-Path $ProjectDir "dist\MoMNativeServer.exe"
if (-not (Test-Path -LiteralPath $NativeServerExe)) { throw "$NativeServerExe was not generated" }

$IsccCandidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
)
$Iscc = $IsccCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $Iscc) {
    throw "Inno Setup 6 was not found (winget install JRSoftware.InnoSetup)"
}
$InnoLicense = Join-Path (Split-Path -Parent $Iscc) "license.txt"
if (-not (Test-Path -LiteralPath $InnoLicense -PathType Leaf)) {
    throw "The Inno Setup licence could not be located"
}
Copy-Item -LiteralPath $InnoLicense -Destination (Join-Path $LicenseDir "INNO-SETUP-LICENSE.txt") -Force
& $Iscc "/DMyAppVersion=$Version" (Join-Path $ProjectDir "installer\MoMRevival.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }

$Installer = Join-Path $ProjectDir "dist\MoMRevivalSetup.exe"
if (-not (Test-Path -LiteralPath $Installer)) { throw "$Installer was not generated" }
$LegacyInstaller = Join-Path $ProjectDir "dist\MoMRevivalInstaller.exe"
if (Test-Path -LiteralPath $LegacyInstaller -PathType Leaf) {
    Remove-Item -LiteralPath $LegacyInstaller -Force
}
Write-Host "Client: $Exe"
Write-Host "  SHA256:  $((Get-FileHash -Algorithm SHA256 -LiteralPath $Exe).Hash)"
Write-Host "Launcher: $LauncherExe"
Write-Host "  SHA256:  $((Get-FileHash -Algorithm SHA256 -LiteralPath $LauncherExe).Hash)"
Write-Host "Server manager: $ManagerExe"
Write-Host "  SHA256:  $((Get-FileHash -Algorithm SHA256 -LiteralPath $ManagerExe).Hash)"
Write-Host "Native server: $NativeServerExe"
Write-Host "  SHA256:  $((Get-FileHash -Algorithm SHA256 -LiteralPath $NativeServerExe).Hash)"
Write-Host "Installer: $Installer"
Write-Host "  SHA256:   $((Get-FileHash -Algorithm SHA256 -LiteralPath $Installer).Hash)"
