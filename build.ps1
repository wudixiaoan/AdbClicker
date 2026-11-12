$ErrorActionPreference = 'Stop'
chcp 65001 > $null
Set-Location -LiteralPath $PSScriptRoot
$adbSource = Join-Path $PSScriptRoot 'vendor\adb'
$adbFiles = @('adb.exe', 'AdbWinApi.dll', 'AdbWinUsbApi.dll', 'NOTICE.txt', 'source.properties')
foreach ($file in $adbFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $adbSource $file))) {
        throw "内置 ADB 文件缺失：$file"
    }
}
$buildPython = Join-Path $PSScriptRoot '.build-venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $buildPython)) {
    python -m venv .build-venv
    if ($LASTEXITCODE -ne 0) { throw '创建打包环境失败' }
}
& $buildPython -m pip install -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw '安装打包依赖失败' }
& $buildPython -m PyInstaller --noconfirm --clean --onefile --windowed --name AdbClicker adb_clicker.py
if ($LASTEXITCODE -ne 0) { throw '生成 EXE 失败' }
$adbDestination = Join-Path $PSScriptRoot 'dist\adb'
New-Item -ItemType Directory -Path $adbDestination -Force > $null
foreach ($file in $adbFiles) {
    Copy-Item -LiteralPath (Join-Path $adbSource $file) -Destination (Join-Path $adbDestination $file) -Force
}
Copy-Item -LiteralPath 'README.md' -Destination 'dist\README.md' -Force
Compress-Archive -LiteralPath 'dist\AdbClicker.exe', 'dist\adb', 'dist\README.md' -DestinationPath 'dist\AdbClicker-portable.zip' -Force
Write-Host '打包完成：dist\AdbClicker-portable.zip。完整解压后双击 AdbClicker.exe。'
