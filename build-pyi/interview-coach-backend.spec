# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['../run_backend.py'],
    pathex=[],
    binaries=[('E:/Coding/Anaconda/Library/bin/ffi-8.dll', '.'), ('E:/Coding/Anaconda/Library/bin/ffi.dll', '.')],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
