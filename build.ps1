$ErrorActionPreference = 'Stop'
chcp 65001 > $null
Set-Location -LiteralPath $PSScriptRoot
$adbSource = Join-Path $PSScriptRoot 'vendor\adb'
$scrcpySource = Join-Path $PSScriptRoot 'vendor\scrcpy'
if (-not (Test-Path -LiteralPath (Join-Path $scrcpySource 'scrcpy.exe'))) { throw '缺少内置 scrcpy' }
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
New-Item -ItemType Directory -Path 'dist\scrcpy' -Force > $null
Get-ChildItem -LiteralPath $scrcpySource -File | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination (Join-Path 'dist\scrcpy' $_.Name) -Force
}
New-Item -ItemType Directory -Path 'dist\configs' -Force > $null
Copy-Item -LiteralPath 'configs\README.txt' -Destination 'dist\configs\README.txt' -Force
Compress-Archive -LiteralPath 'dist\AdbClicker.exe', 'dist\adb', 'dist\scrcpy', 'dist\README.md' -DestinationPath 'dist\AdbClicker-portable.zip' -Force
# 只添加目录说明，避免将本机用户配置混入发布包。
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [System.IO.Compression.ZipFile]::Open((Join-Path $PSScriptRoot 'dist\AdbClicker-portable.zip'), 'Update')
try {
    [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, (Join-Path $PSScriptRoot 'configs\README.txt'), 'configs/README.txt') > $null
} finally {
    $archive.Dispose()
}
Write-Host '打包完成：dist\AdbClicker-portable.zip。完整解压后双击 AdbClicker.exe。'
