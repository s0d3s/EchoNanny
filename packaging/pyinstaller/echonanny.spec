# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


_spec_dir = Path(globals().get("SPECPATH", Path.cwd())).resolve()
ROOT = _spec_dir.parents[1]

datas = [
    (str(ROOT / "backend" / "app" / "webui"), "app/webui"),
    (str(ROOT / "backend" / "assets"), "assets"),
    (str(ROOT / "backend" / "app" / ".env.example"), "app"),
]

hiddenimports = [
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.websockets",
    "passlib.handlers.bcrypt",
]

a = Analysis(
    [str(ROOT / "backend" / "app" / "cli.py")],
    pathex=[str(ROOT / "backend")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    [],
    exclude_binaries=True,
    name="echonanny",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="echonanny",
)
