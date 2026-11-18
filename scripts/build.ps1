[CmdletBinding()]
param(
    [string]$Bash = 'C:\msys64\usr\bin\bash.exe',
    [string]$InnoCompiler = "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    [string]$ModelDirectory,
    [ValidateSet('All', 'Freeze', 'Package')] [string]$Phase = 'All'
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Push-Location $root
$originalPath = $env:PATH
$originalPyInstallerCache = $env:PYINSTALLER_CONFIG_DIR
try {
    $python = (Resolve-Path .venv\Scripts\python.exe).Path
    $base = (& $python -c 'import sys; print(sys.base_prefix)').Trim()
    if (-not (Test-Path build\codecs\libwinpthread-1.dll)) {
        & $Bash ./packaging/build-codecs.sh
        if ($LASTEXITCODE) {throw 'FFmpeg build failed'}
    }
    if (-not (Test-Path build\qt-sources\Qt-notices.zip) -or -not (Test-Path dist\Qt-6.12.0-Corresponding-Sources.zip)) {
        & $python packaging\qt_sources.py
        if ($LASTEXITCODE) {throw 'Failed to prepare Qt corresponding sources'}
    }
    # Discard unrelated directories on the developer's PATH. In particular,
    # Qt 6 uses the Windows ICU API, which incompatible third-party icuuc.dlls can shadow.
    $env:PATH = "$root\.venv\Scripts;$base;$base\DLLs;$root\.venv\Lib\site-packages\PySide6;$env:SystemRoot\System32;$env:SystemRoot"
    $env:PYINSTALLER_CONFIG_DIR = Join-Path $root "build\pyinstaller-cache"
    if ($Phase -ne 'Package') {
        & $python -m PyInstaller --clean --noconfirm --workpath build\isolated packaging\VoxMasterAI.spec
        if ($LASTEXITCODE) {throw 'PyInstaller failed'}
        & $python packaging\stage.py --freeze
        if ($LASTEXITCODE) {throw 'Staging failed'}
    }
    $outdir = (Resolve-Path dist).Path
    $report = Join-Path $root ("build\bundle-" + [guid]::NewGuid() + ".json")
    $params = @('--verify-package', ('"' + $report + '"'))
    if ($ModelDirectory) { $params += ('"' + (Resolve-Path $ModelDirectory).Path + '"') }
    $proc = Start-Process -FilePath "$outdir\VoxMasterAI\VoxMasterAI.exe" -ArgumentList $params -PassThru -WindowStyle Hidden
    if (-not $proc.WaitForExit(180000)) { $proc.Kill(); throw 'Bundled app check timed out' }
    if ($proc.ExitCode -ne 0 -or -not (Test-Path $report)) { throw "Bundled app check failed. Report $report" }
    Get-Content -Raw $report
    if ($Phase -eq 'Freeze') { return }
    & $python packaging\stage.py --package
    if ($LASTEXITCODE) {throw 'Document packaging or source verification failed'}
    & "$env:SystemRoot\System32\tar.exe" -a -cf "$outdir\VoxMasterAI-Portable.zip" -C $outdir VoxMasterAI
    if ($LASTEXITCODE) {throw 'Portable zip failed'}
    if (-not (Test-Path -LiteralPath $InnoCompiler)) {
        $InnoCompiler = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
    }
    & $InnoCompiler /Qp packaging\VoxMasterAI.iss
    if ($LASTEXITCODE) {throw 'Inno Setup failed'}
    & "$env:SystemRoot\System32\tar.exe" -a -cf "$outdir\VoxMasterAI-Source.zip" --exclude "__pycache__" --exclude "*.pyc" --exclude ".pytest_cache" app.py vox scripts packaging tests docs .github requirements.txt README.md CHANGELOG.md CONTRIBUTING.md SECURITY.md CODE_OF_CONDUCT.md .gitignore
    if ($LASTEXITCODE) {throw 'Source zip failed'}
    Get-FileHash "$outdir\VoxMasterAI-Portable.zip","$outdir\VoxMasterAI-Setup.exe","$outdir\VoxMasterAI-Source.zip","$outdir\Qt-6.12.0-Corresponding-Sources.zip" |
        ForEach-Object { $_.Hash.ToLower() + '  ' + (Split-Path $_.Path -Leaf) } |
        Set-Content "$outdir\SHA256SUMS.txt" -Encoding ascii
} finally {
    $env:PYINSTALLER_CONFIG_DIR = $originalPyInstallerCache
    $env:PATH = $originalPath
    Pop-Location
}

