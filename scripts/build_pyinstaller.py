from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "packaging" / "pyinstaller" / "echonanny.spec"
DIST_PATH = ROOT / "packaging" / "pyinstaller" / "dist"
BUILD_PATH = ROOT / "packaging" / "pyinstaller" / "build"


def run(cmd: list[str]) -> None:
    print(f"[pyinstaller] run: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def _best_effort_stop_running_echonanny() -> None:
    # Prevent WinError 5 when previous built echonanny.exe is still running.
    try:
        subprocess.run(["taskkill", "/IM", "echonanny.exe", "/F"], check=False, capture_output=True, text=True)
    except Exception:
        pass


def _clean_dist_dir_with_retry(path: Path, retries: int = 5, delay_sec: float = 0.5) -> None:
    if not path.exists():
        return

    last_error: Exception | None = None
    for _ in range(retries):
        try:
            shutil.rmtree(path)
            return
        except Exception as exc:  # pragma: no cover - OS/process state dependent
            last_error = exc
            time.sleep(delay_sec)

    raise RuntimeError(
        f"Unable to clean dist folder '{path}'. Make sure no echonanny.exe is running and retry."
    ) from last_error


def main() -> int:
    run([sys.executable, str(ROOT / "scripts" / "sync_webui_bundle.py")])

    _best_effort_stop_running_echonanny()
    _clean_dist_dir_with_retry(DIST_PATH / "echonanny")

    if importlib.util.find_spec("PyInstaller") is None:
        print(
            "[pyinstaller] PyInstaller is not installed in the active environment.\n"
            f"[pyinstaller] install it with: {sys.executable} -m pip install pyinstaller\n"
            f"[pyinstaller] or install build extras: {sys.executable} -m pip install -e .[build]",
            file=sys.stderr,
        )
        return 1

    run([
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--distpath",
        str(DIST_PATH),
        "--workpath",
        str(BUILD_PATH),
        str(SPEC_PATH),
    ])
    print(f"[pyinstaller] output: {DIST_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
