[CmdletBinding()]
param(
    [string]$ModelDirectory,
    [string]$PreviousInstaller,
    [switch]$IsolatedRegistration,
    [string]$PackageDirectory,
    [string]$InnoCompiler = "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$folder = Join-Path $root ("build\accept-" + [guid]::NewGuid())
$packages = if ($PackageDirectory) { (Resolve-Path -LiteralPath $PackageDirectory).Path } else { Join-Path $root 'dist' }
$registryKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{88A1E9AC-B8AB-4BB9-B1B8-FC4046736E24}_is1'
$productionRegistry = $registryKey
$productionInstall = Get-ItemProperty -LiteralPath $registryKey -ErrorAction SilentlyContinue
$userShortcut = Join-Path ([Environment]::GetFolderPath('Programs')) 'VoxMaster AI\VoxMaster AI.lnk'
$previousShortcut = if (Test-Path -LiteralPath $userShortcut) { (Get-FileHash -LiteralPath $userShortcut).Hash }
$isolated = $IsolatedRegistration -or $null -ne $productionInstall
if ($isolated) {
    $testId = [guid]::NewGuid().ToString().ToUpper()
    $registryKey = $registryKey.Replace('88A1E9AC-B8AB-4BB9-B1B8-FC4046736E24', $testId)
    if (-not (Test-Path -LiteralPath $InnoCompiler)) {
        $InnoCompiler = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
    }
}
$null = New-Item -ItemType Directory -Path $folder
$install = Join-Path $folder 'Installed'
$installerFlags = @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/NOICONS',('/DIR="' + $install + '"'))
$originalPath = $env:PATH
$priorData = $env:VOXMASTER_DATA

function RunChecked([string]$Executable, [string[]]$Arguments, [int]$Timeout=180000) {
    $proc = Start-Process -FilePath $Executable -ArgumentList $Arguments -WindowStyle Hidden -PassThru
    if (-not $proc.WaitForExit($Timeout)) { $proc.Kill(); throw "$Executable timed out" }
    if ($proc.ExitCode -ne 0) { throw "$Executable exited $($proc.ExitCode)" }
}

# Compile each release's original setup script against the files in that exact
# portable archive. Isolate both its registration and its Start Menu group.
function New-IsolatedInstaller([string]$ReleaseFolder, [string]$Label) {
    $recipe = Join-Path $folder $Label
    $null = New-Item -ItemType Directory -Path "$recipe\dist" -Force
    $tar = "$env:SystemRoot\System32\tar.exe"
    & $tar -xf "$ReleaseFolder\VoxMasterAI-Source.zip" -C $recipe packaging/VoxMasterAI.iss packaging/VoxMasterAI.ico
    if ($LASTEXITCODE) { throw 'Cannot extract archived installer recipe' }
    & $tar -xf "$ReleaseFolder\VoxMasterAI-Portable.zip" -C "$recipe\dist"
    if ($LASTEXITCODE) { throw 'Cannot extract archived payload' }
    $iss = "$recipe\packaging\VoxMasterAI.iss"
    $original = [IO.File]::ReadAllText($iss)
    $oldLine = 'AppId={{88A1E9AC-B8AB-4BB9-B1B8-FC4046736E24}'
    if (([regex]::Matches($original, [regex]::Escape($oldLine))).Count -ne 1) {
        throw 'Unexpected AppId in installer recipe'
    }
    $oldGroup = 'DefaultGroupName=VoxMaster AI'
    if (([regex]::Matches($original, [regex]::Escape($oldGroup))).Count -ne 1) { throw 'Unexpected Start Menu group' }
    $isolatedRecipe = $original.Replace($oldLine, ('AppId={{' + $testId + '}')).Replace($oldGroup, "DefaultGroupName=VoxMaster QA $testId")
    [IO.File]::WriteAllText($iss, $isolatedRecipe, [Text.UTF8Encoding]::new($true))
    & $InnoCompiler /Q $iss | Out-Host
    if ($LASTEXITCODE) { throw "Could not compile isolated $Label installer" }
    return "$recipe\dist\VoxMasterAI-Setup.exe"
}

try {
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
    $env:VOXMASTER_DATA = Join-Path $folder 'UserData'
    & "$env:SystemRoot\System32\tar.exe" -xf "$packages\VoxMasterAI-Portable.zip" -C $folder
    if ($LASTEXITCODE) { throw 'Archive extraction failed' }
    $version = (Get-Item "$folder\VoxMasterAI\VoxMasterAI.exe").VersionInfo.ProductVersion
    $preserved = @{}
    $currentInstaller = "$packages\VoxMasterAI-Setup.exe"
    if ($isolated) {
        $currentInstaller = New-IsolatedInstaller $packages 'new-recipe'
        if ($PreviousInstaller) {
            $PreviousInstaller = New-IsolatedInstaller (Split-Path (Resolve-Path $PreviousInstaller).Path -Parent) 'old-recipe'
        }
    }
    try {
        if ($PreviousInstaller) {
            RunChecked (Resolve-Path -LiteralPath $PreviousInstaller).Path $installerFlags
            $oldVersion = (Get-ItemProperty -LiteralPath $registryKey).DisplayVersion
            if ([version]$oldVersion -ge [version]$version) { throw "Expected an older installation, got $oldVersion" }
            $audio = Join-Path $folder 'upgrade.wav'
            Copy-Item -LiteralPath "$root\tests\fixtures\fleurs-mandarin.wav" -Destination $audio
            $settings = Join-Path $env:VOXMASTER_DATA 'settings.json'
            $legacy = Start-Process "$install\VoxMasterAI.exe" -ArgumentList ('"' + $audio + '"') -WindowStyle Hidden -PassThru
            try {
                # Exercise recovery from an interrupted session. Only terminate the
                # isolated old process after its real import and atomic saves finish.
                $deadline = [DateTime]::UtcNow.AddSeconds(90)
                do {
                    Start-Sleep -Milliseconds 150
                    $recovery = Get-ChildItem "$env:VOXMASTER_DATA\recovery" -Filter '*.voxproj' -ErrorAction SilentlyContinue | Select-Object -First 1
                    if ($legacy.HasExited -or [DateTime]::UtcNow -gt $deadline) { throw 'Old application did not save a recovery project and settings' }
                } until ($recovery -and (Test-Path -LiteralPath $settings))
            } finally {
                if (-not $legacy.HasExited) { $legacy.Kill(); $legacy.WaitForExit() }
            }
            foreach ($path in @($audio, $settings, $recovery.FullName)) {
                $preserved[$path] = (Get-FileHash -LiteralPath $path).Hash
            }
        }
        RunChecked $currentInstaller $installerFlags
        $installedHash = (Get-FileHash "$install\VoxMasterAI.exe").Hash
        if ($installedHash -ne (Get-FileHash "$folder\VoxMasterAI\VoxMasterAI.exe").Hash) {
            throw 'Installed executable differs from portable release'
        }
        $displayVersion = (Get-ItemProperty -LiteralPath $registryKey).DisplayVersion
        if ($displayVersion -ne $version) { throw "Uninstaller version mismatch: $displayVersion vs $version" }
        foreach ($name in @('Installed','VoxMasterAI')) {
            $report = Join-Path $folder "$name.json"
            $cli = @('--verify-package',('"' + $report + '"'))
            if ($ModelDirectory) { $cli += ('"' + (Resolve-Path $ModelDirectory).Path + '"') }
            if ($PreviousInstaller) { $cli += @('--recover-project',('"' + $recovery.FullName + '"')) }
            RunChecked (Join-Path $folder "$name\VoxMasterAI.exe") $cli
            $result = Get-Content $report -Raw -Encoding utf8 | ConvertFrom-Json
            if ($result.status -ne 'PASS' -or $result.version -ne $version) { throw "Failed $report" }
            if ($PreviousInstaller -and ($result.recovery.source -ne $audio -or $result.recovery.frames -ne 457758)) {
                throw "Old project did not restore the complete 10.38 second recording"
            }
        }
    } finally {
        if (Test-Path "$install\unins000.exe") {
            RunChecked "$install\unins000.exe" @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART')
        }
    }
    if ((Test-Path "$install\VoxMasterAI.exe") -or (Test-Path $registryKey)) { throw 'Uninstall incomplete' }
    foreach ($entry in $preserved.GetEnumerator()) {
        if ((Get-FileHash -LiteralPath $entry.Key).Hash -ne $entry.Value) { throw "Changed user file: $($entry.Key)" }
    }
    if ($PreviousInstaller) {
        $registration = if ($isolated) { 'isolated-AppId' } else { 'production-AppId' }
        [ordered]@{from=$oldVersion; to=$version; registration=$registration; exeSHA256=$installedHash; unchangedSettingsProjectAudio=$preserved; uninstall='PASS'} |
            ConvertTo-Json | Set-Content -LiteralPath "$folder\upgrade.json" -Encoding utf8
    }
    if ($isolated) {
        $currentShortcut = if (Test-Path -LiteralPath $userShortcut) { (Get-FileHash -LiteralPath $userShortcut).Hash }
        if ($previousShortcut -ne $currentShortcut) { throw 'Start Menu shortcut changed' }
    }
    if ($productionInstall) {
        $after = Get-ItemProperty -LiteralPath $productionRegistry
        if ($after.DisplayVersion -ne $productionInstall.DisplayVersion -or $after.InstallLocation -ne $productionInstall.InstallLocation) {
            throw 'Existing production installation registration changed'
        }
    }
    Write-Output "PASS Windows installation, portable archive and diagnostics: $folder"
} finally {
    $env:PATH = $originalPath
    $env:VOXMASTER_DATA = $priorData
}

