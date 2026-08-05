# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：情侣套件 onedir 模式。

构建：
  开发机：pip install -r requirements.txt pyinstaller
         pyinstaller couple_suite.spec --noconfirm
  产物：dist/CoupleSuite/ 目录（整个目录拷给用户运行 CoupleSuite.exe）
"""

block_cipher = None

a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('assets/china_geo.json', 'assets'),
        ('assets/default_album', 'assets/default_album'),
        ('assets/icon.ico', 'assets'),
    ],
    hiddenimports=[
        # PySide6 基础
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        # Pillow
        'PIL._tkinter_finder',
        # cryptography
        'cryptography.fernet',
        # matplotlib（心情曲线/雷达图）
        'matplotlib',
        'matplotlib.backends.backend_qtagg',
        'matplotlib.backends.backend_agg',
        # 项目内包
        'app_paths',
        'common_utils',
        'autostart',
        'backup',
        'font_utils',
        'migration',
        'onboarding',
        'settings_window',
        'stats_window',
        'tray',
        'version',
        'DesktopPhotoFrame',
        'DesktopPhotoFrame.config',
        'DesktopPhotoFrame.image_processor',
        'DesktopPhotoFrame.frame_window',
        'DesktopPhotoFrame.gallery_window',
        'DesktopPhotoFrame.heart_popup',
        'DesktopPhotoFrame.tray',
        'DesktopPhotoFrame.main',
        'DesktopMailbox',
        'DesktopMailbox.config',
        'DesktopMailbox.crypto',
        'DesktopMailbox.letter_store',
        'DesktopMailbox.compose_window',
        'DesktopMailbox.inbox_window',
        'DesktopMailbox.read_letter_window',
        'DesktopMailbox.notifier',
        'DesktopMailbox.tray',
        'DesktopMailbox.anniversary',
        'DesktopMailbox.sync',
        'DesktopMailbox.cloud_sync',
        'DesktopMailbox.main',
        'DailyCheckin',
        'DailyCheckin.store',
        'DailyCheckin.calendar_widget',
        'DailyCheckin.mood_chart',
        'DailyCheckin.checkin_window',
        'MovieBoard',
        'MovieBoard.store',
        'MovieBoard.scraper',
        'MovieBoard.report_generator',
        'MovieBoard.board_window',
        'TravelMap',
        'TravelMap.store',
        'TravelMap.city_picker',
        'TravelMap.map_window',
        'TravelMap.china_outline',
        'TravelMap.china_map_widget',
        'Gomoku',
        'Gomoku.board_widget',
        'Gomoku.game_window',
        'Gomoku.store',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 排除不需要的大模块减小体积
        'tkinter',
        'scipy',
        'pandas',
        'playwright',
        'PySide6.Qt3D',
        'PySide6.QtCharts',
        'PySide6.QtDataVisualization',
        'PySide6.QtMultimedia',
        # QtNetwork 未使用（sync/云同步走标准库 urllib.request）
        'PySide6.QtNetwork',
        'PySide6.QtSql',
        'PySide6.QtTest',
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineWidgets',
        'PySide6.QtWebChannel',
        'PySide6.QtWebSockets',
        'PySide6.QtXml',
        'PySide6.QtDBus',
        'PySide6.QtBluetooth',
        'PySide6.QtOpenGL',
        'PySide6.QtOpenGLWidgets',
        'PySide6.QtPositioning',
        'PySide6.QtPrintSupport',
        'PySide6.QtPdf',
        'PySide6.QtQml',
        'PySide6.QtQuick',
        'PySide6.QtQuick3D',
        'PySide6.QtRemoteObjects',
        'PySide6.QtScxml',
        'PySide6.QtSensors',
        'PySide6.QtSerialPort',
        'PySide6.QtStateMachine',
        'PySide6.QtTextToSpeech',
        'PySide6.QtSvg',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='CoupleSuite',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # 无控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='CoupleSuite',
)
