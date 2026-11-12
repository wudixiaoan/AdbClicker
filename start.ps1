$ErrorActionPreference = 'Stop'
chcp 65001 > $null
Set-Location -LiteralPath $PSScriptRoot
python (Join-Path $PSScriptRoot 'adb_clicker.py')
