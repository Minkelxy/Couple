# CoupleSuite Windows 打包脚本
# 用法: 在 PowerShell 中运行 .\build-windows.ps1
# 产物: dist\CoupleSuite\CoupleSuite.exe  +  压缩包 dist\CoupleSuite-<版本>-windows-x64.zip

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

# 1. 基础检查
Write-Host "==> [1/5] 检查环境" -ForegroundColor Cyan
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Error "找不到 python.exe，请先安装 Python 3.10+ 并加入 PATH。"
    exit 1
}
Write-Host "Python 路径: $($py.Source)"
& python -c "import sys; print(f'Python {sys.version}')"

# 2. 装依赖
Write-Host "`n==> [2/5] 安装依赖（pip install -r requirements.txt pyinstaller）" -ForegroundColor Cyan
& python -m pip install --upgrade pip
& python -m pip install -r requirements.txt
& python -m pip install --no-cache-dir pyinstaller pillow-avif-plugin

# 3. 构建
Write-Host "`n==> [3/5] PyInstaller 构建" -ForegroundColor Cyan
if (Test-Path build) { Remove-Item -Recurse -Force build }
if (Test-Path dist\CoupleSuite) { Remove-Item -Recurse -Force dist\CoupleSuite }
& python -m PyInstaller couple_suite.spec --noconfirm
if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller 构建失败，退出码 $LASTEXITCODE"
    exit 1
}

# 4. 读版本号
Write-Host "`n==> [4/5] 读取版本号" -ForegroundColor Cyan
$ver = & python -c "import ast; print(ast.literal_eval(open('version.py', encoding='utf-8').read().split('__version__ = ')[1].split(chr(10))[0]))"
Write-Host "版本: $ver"
$ZipName = "CoupleSuite-$ver-windows-x64.zip"

# 5. 打包 zip
Write-Host "`n==> [5/5] 生成 zip 产物: $ZipName" -ForegroundColor Cyan
$ZipPath = Join-Path $ProjectRoot "dist\$ZipName"
if (Test-Path $ZipPath) { Remove-Item -Force $ZipPath }
Compress-Archive -Path "dist\CoupleSuite" -DestinationPath $ZipPath -Force

$sizeMB = [math]::Round((Get-Item $ZipPath).Length / 1MB, 1)
Write-Host "`n构建成功 ✓" -ForegroundColor Green
Write-Host "  - exe: $ProjectRoot\dist\CoupleSuite\CoupleSuite.exe"
Write-Host "  - zip: $ZipPath  ($sizeMB MB)"
