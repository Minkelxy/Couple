# 构建说明（Windows）

## 方式一：一键脚本（推荐）

在 PowerShell 里执行：

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned -Force
.\build-windows.ps1
```

完成后产物在：

```
dist\CoupleSuite\CoupleSuite.exe
```

整个 `dist\CoupleSuite` 目录打包给用户即可。

## 方式二：手动

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt pyinstaller
pyinstaller couple_suite.spec --noconfirm
```

## 方式三：GitHub Actions（推荐给维护者）

任何提交打 `vX.Y.Z` 格式的 tag，workflow 会自动：

1. 在 Windows 最新 runner 上装依赖；
2. 用 `couple_suite.spec` 构建 onedir 包；
3. 打包成 `CoupleSuite-vX.Y.Z-windows-x64.zip`；
4. 在仓库 **Releases** 页生成一个带自动 Release Notes 的 release，把 zip 挂到 Assets 里。

手动触发：Actions → Build & Release Windows exe → Run workflow。

---

## 给最终用户的安装说明

1. 下载 `CoupleSuite-vX.Y.Z-windows-x64.zip`；
2. 解压到任意目录（推荐 `D:\CoupleSuite` 或 `C:\Users\你\AppData\Local\CoupleSuite`，**不要**放到 `Program Files`，否则无管理员权限时写配置会失败）；
3. 双击 `CoupleSuite.exe` 打开；
4. 所有配置/信件/照片默认保存在 `%APPDATA%\CoupleSuite`，卸载时直接删 exe 目录 + 手动删 `%APPDATA%\CoupleSuite` 即可（绿色软件，不写注册表除了“开机自启动”功能）。

## 常见问题

**Q: 双击 exe 没反应？**
A: 大概率 Windows Defender 拦截。打开 Windows 安全中心 → 病毒和威胁防护 → 保护历史记录，找到拦截项点「已允许」。或者把整个 CoupleSuite 目录加入排除项。

**Q: 杀毒软件报病毒？**
A: PyInstaller 打包的 exe 容易被误报，上传到 Virustotal 能看到只有一两家报毒。把目录加入杀毒软件排除项即可。

**Q: 第一次打开是英文/中文？**
A: 跟随系统语言，UI 目前只有中文。
