"""Exercise the real PowerShell recipe helper without installing an application."""
import json
import os
import subprocess
from pathlib import Path
from zipfile import ZipFile

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(os.name != 'nt', reason='Windows installer recipe uses native PowerShell and tar')
def test_isolated_recipe_uses_canonical_payload_paths(tmp_path):
    release = tmp_path / 'release'
    release.mkdir()
    original = (
        '[Setup]\n'
        'AppId={{88A1E9AC-B8AB-4BB9-B1B8-FC4046736E24}\n'
        'DefaultGroupName=VoxMaster AI\n'
        '[Files]\n'
        'Source: "..\\dist\\VoxMasterAI\\*"; DestDir: "{app}"; Flags: recursesubdirs\n'
    )
    with ZipFile(release / 'VoxMasterAI-Source.zip', 'w') as archive:
        archive.writestr('packaging/VoxMasterAI.iss', original)
        archive.writestr('packaging/VoxMasterAI.ico', b'synthetic icon, compiler is stubbed')
    deep_directory = 'deep-' + ('x' * 120)
    deep_member = f'VoxMasterAI/{deep_directory}/marker.bin'
    with ZipFile(release / 'VoxMasterAI-Portable.zip', 'w') as archive:
        archive.writestr('VoxMasterAI/payload.bin', b'synthetic installer payload')
        archive.writestr(deep_member, b'deep payload reached through alias')
    compiler = tmp_path / 'compiler.ps1'
    compiler.write_text(
        "$ErrorActionPreference = 'Stop'\n"
        "$text = [IO.File]::ReadAllText($args[-1])\n"
        "$match = [regex]::Match($text, '(?m)^Source: \"([^\"]+)\"')\n"
        "if (-not $match.Success) { throw 'Missing payload source' }\n"
        "$payload = $match.Groups[1].Value\n"
        "if (-not [IO.Path]::IsPathRooted($payload) -or $payload.Contains('\\..\\')) {\n"
        "    throw 'Payload source retains a relative path expansion'\n"
        "}\n"
        "$payloadRoot = $payload.Substring(0, $payload.Length - 2)\n"
        f"$marker = Join-Path $payloadRoot '{deep_directory}\\marker.bin'\n"
        "if (-not [IO.File]::Exists($marker)) { throw 'Deep payload is not reachable through alias' }\n"
        "[IO.File]::WriteAllText((Join-Path $PSScriptRoot 'compiled-recipe.txt'), $text)\n",
        encoding='utf-8',
    )
    runner = tmp_path / 'run-helper.ps1'
    runner.write_text(
        'param($SourceScript, $Work, $Release, $Compiler, $Report)\n'
        "$ErrorActionPreference = 'Stop'\n"
        '$folder = $Work\n'
        "$testId = '00000000-0000-0000-0000-000000000051'\n"
        '$InnoCompiler = $Compiler\n'
        '$tokens = $null; $errors = $null\n'
        '$ast = [Management.Automation.Language.Parser]::ParseFile($SourceScript, [ref]$tokens, [ref]$errors)\n'
        '$definition = $ast.Find({ param($node)\n'
        '    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and '
        "$node.Name -eq 'New-IsolatedInstaller'\n"
        '}, $true)\n'
        "if (-not $definition) { throw 'Missing installer helper' }\n"
        '. ([scriptblock]::Create($definition.Extent.Text))\n'
        "$installer = New-IsolatedInstaller $Release 'current'\n"
        "@{installer=$installer; compiled=(Test-Path (Join-Path (Split-Path $Compiler) 'compiled-recipe.txt'))} |\n"
        '    ConvertTo-Json | Set-Content -LiteralPath $Report -Encoding utf8\n',
        encoding='utf-8',
    )
    work = tmp_path / ('work-root-' + ('w' * 72)) / 'work'
    work.parent.mkdir(parents=True)
    long_member = work / 'current' / 'dist' / Path(*deep_member.split('/'))
    assert len(str(long_member)) > 260
    report = tmp_path / 'result.json'
    completed = subprocess.run(
        ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(runner),
         str(ROOT / 'scripts/verify-release.ps1'), str(work), str(release), str(compiler), str(report)],
        check=False, capture_output=True, timeout=45,
    )
    assert completed.returncode == 0, completed.stderr.decode('utf-8', errors='replace')
    result = json.loads(report.read_text(encoding='utf-8-sig'))
    assert result['compiled'] is True
    expected = work / 'current/dist/VoxMasterAI-Setup.exe'
    assert Path(result['installer']) == expected
    assert long_member.is_file()
    recipe = (tmp_path / 'compiled-recipe.txt').read_text(encoding='utf-8-sig')
    assert 'AppId={{00000000-0000-0000-0000-000000000051}' in recipe
    assert 'DefaultGroupName=VoxMaster QA 00000000-0000-0000-0000-000000000051' in recipe
    source = next(line.split('"', 2)[1] for line in recipe.splitlines()
                  if line.startswith('Source: "'))
    assert source.lower().startswith('source:') is False
    assert 'vox-qa-' in source.lower()
    assert not source.lower().startswith(str(work).lower())
    assert '\\..\\' not in source
    assert len(source) < len(str(work / 'current/dist/VoxMasterAI'))
    assert not Path(source[:-2]).exists()
