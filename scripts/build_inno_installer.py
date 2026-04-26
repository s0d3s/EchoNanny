from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ISS_PATH = ROOT / "packaging" / "inno" / "echonanny.iss"
DIST_PATH = ROOT / "packaging" / "pyinstaller" / "dist" / "echonanny"
ISCC_CANDIDATES = [
    shutil.which("iscc"),
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
]


def resolve_iscc() -> str | None:
    for candidate in ISCC_CANDIDATES:
        if not candidate:
            continue
        path = Path(candidate)
        if path.exists():
            return str(path)
    return None


def main() -> int:
    iscc = resolve_iscc()
    if not iscc:
        print("[inno] ISCC.exe not found. Install Inno Setup 6 or add iscc to PATH.", file=sys.stderr)
        return 1

    if not DIST_PATH.exists() or not DIST_PATH.is_dir():
        print(
            "[inno] PyInstaller dist folder not found. Build it first with:\n"
            f"[inno]   {sys.executable} {ROOT / 'scripts' / 'build_pyinstaller.py'}\n"
            f"[inno] expected: {DIST_PATH}",
            file=sys.stderr,
        )
        return 1

    main_exe = DIST_PATH / "echonanny.exe"
    if not main_exe.exists():
        print(f"[inno] Missing expected executable: {main_exe}", file=sys.stderr)
        return 1

    dist_for_iss = str(DIST_PATH).replace("\\", "\\\\")

    cmd = [
        iscc,
        f"/DMyDistDir={dist_for_iss}",
        str(ISS_PATH),
    ]
    print(f"[inno] run: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)
    print(f"[inno] built installer from: {ISS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
