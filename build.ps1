# 重新打包脚本：生成 dist\鼠标脚本工具.exe
# 用法：pwsh -NoProfile -File build.ps1
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
python -m PyInstaller --onefile --windowed --clean --name "鼠标脚本工具" main.py
Write-Output "打包完成：$PSScriptRoot\dist\鼠标脚本工具.exe"
