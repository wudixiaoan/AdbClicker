$ErrorActionPreference = 'Stop'
chcp 65001 > $null
Set-Location -LiteralPath $PSScriptRoot
$buildPython = Join-Path $PSScriptRoot '.build-venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $buildPython)) {
    python -m venv .build-venv
    if ($LASTEXITCODE -ne 0) { throw '创建打包环境失败' }
}
& $buildPython -m pip install -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw '安装打包依赖失败' }
& $buildPython -m PyInstaller --noconfirm --clean --onefile --windowed --name AdbClicker adb_clicker.py
if ($LASTEXITCODE -ne 0) { throw '生成 EXE 失败' }
Write-Host '打包完成：dist\AdbClicker.exe，可双击启动。'
