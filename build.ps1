# 重新打包脚本
# 用法：
#   pwsh -NoProfile -File build.ps1          # 卡密验证版（默认，产物 dist\鼠标脚本工具.exe）
#   pwsh -NoProfile -File build.ps1 -Full    # 完整/纯净版（无卡密验证，产物 dist_full\鼠标脚本工具.exe）
param([switch]$Full)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

if ($Full) {
    # 临时关闭卡密验证开关 → 打包 → 还原
    (Get-Content -Encoding UTF8 main.py) -replace
        'REQUIRE_LICENSE = True', 'REQUIRE_LICENSE = False' |
        Set-Content -Encoding UTF8 main.py
    try {
        python -m PyInstaller --onefile --windowed --clean --name "鼠标脚本工具" `
            --distpath dist_full main.py
        Write-Output "打包完成（纯净版）：$PSScriptRoot\dist_full\鼠标脚本工具.exe"
    } finally {
        (Get-Content -Encoding UTF8 main.py) -replace
            'REQUIRE_LICENSE = False', 'REQUIRE_LICENSE = True' |
            Set-Content -Encoding UTF8 main.py
    }
} else {
    python -m PyInstaller --onefile --windowed --clean --name "鼠标脚本工具" main.py
    Write-Output "打包完成（卡密版）：$PSScriptRoot\dist\鼠标脚本工具.exe"
}
