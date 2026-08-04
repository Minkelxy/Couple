# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：情侣套件 onedir 模式。"""

block_cipher = None

a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('assets/china_geo.json', 'assets'),
        ('assets/default_album', 'assets/default_album'),
    ],
    hiddenimports=[
        # PySide6 插件
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        # Pillow
        'PIL._tkinter_finder',
        # cryptography
        'cryptography.fernet',
        # matplotlib 后端（心情曲线/雷达图需要）
        'matplotlib',
        'matplotlib.backends.backend_qtagg',
        'matplotlib.backends.backend_agg',
        # 项目内包（确保被收集）
        'DesktopPhotoFrame',
        'DesktopPhotoFrame.config',
        'DesktopPhotoFrame.image_processor',
        'DesktopPhotoFrame.frame_window',
        'DesktopPhotoFrame.gallery_window',
        'DesktopPhotoFrame.heart_popup',
        'DesktopPhotoFrame.tray',
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
        # 四大新模块
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
        'MusicRadar',
        'MusicRadar.store',
        'MusicRadar.mood_analyzer',
        'MusicRadar.scraper',
        'MusicRadar.radar_window',
        # 五子棋
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
        'PySide6.QtNetwork',
        'PySide6.QtSql',
        'PySide6.QtTest',
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineWidgets',
        'PySide6.QtWebChannel',
        'PySide6.QtWebSockets',
        'PySide6.QtXml',
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
