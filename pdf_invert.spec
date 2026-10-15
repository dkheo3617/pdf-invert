# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 빌드 설정 (macOS / Windows 공용)
import sys

APP = "PDFInvert"
DISPLAY = "PDF색상반전"
VERSION = "2.0.0"

a = Analysis(
    ["src/app.py"],
    pathex=["src"],
    datas=[("assets/icon.png", "assets")],
    excludes=["tkinter", "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick",
              "PySide6.QtWebEngineCore", "PySide6.QtMultimedia", "PySide6.QtPdf"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name=APP,
    console=False,
    icon="assets/icon.ico" if sys.platform == "win32" else "assets/icon.png",
)
coll = COLLECT(exe, a.binaries, a.datas, name=APP)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{DISPLAY}.app",
        icon="assets/icon.png",
        bundle_identifier="kr.gwasaram.pdfinvert",
        version=VERSION,
        info_plist={
            "CFBundleDisplayName": DISPLAY,
            "CFBundleName": DISPLAY,
            "CFBundleShortVersionString": VERSION,
            "NSHighResolutionCapable": True,
            "CFBundleDocumentTypes": [{
                "CFBundleTypeName": "PDF",
                "CFBundleTypeRole": "Viewer",
                "LSHandlerRank": "Alternate",
                "LSItemContentTypes": ["com.adobe.pdf", "public.folder"],
            }],
        },
    )
