from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = ROOT / "dist"


def run(cmd: list[str]) -> None:
    print(f"[wheels] run: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def _clean_dist() -> None:
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    DIST_DIR.mkdir(parents=True, exist_ok=True)


def _ensure_build_installed() -> bool:
    try:
        import build  # noqa: F401
    except Exception:
        print(
            "[wheels] Missing 'build' package in active environment.\n"
            f"[wheels] install it with: {sys.executable} -m pip install build\n"
            f"[wheels] or install build extras: {sys.executable} -m pip install -e .[build]",
            file=sys.stderr,
        )
        return False
    return True


def _validate_wheel_tags() -> bool:
    wheels = sorted(DIST_DIR.glob("*.whl"))
    if not wheels:
        print("[wheels] No wheel files found in dist/", file=sys.stderr)
        return False

    bad = [w.name for w in wheels if not w.name.endswith("py3-none-any.whl")]
    if bad:
        print(
            "[wheels] Expected universal pure-Python wheels with tag 'py3-none-any'.\n"
            f"[wheels] Non-universal wheels detected: {bad}",
            file=sys.stderr,
        )
        return False

    for wheel in wheels:
        print(f"[wheels] built: {wheel}")
    return True


def main() -> int:
    run([sys.executable, str(ROOT / "scripts" / "sync_webui_bundle.py")])

    if not _ensure_build_installed():
        return 1

    _clean_dist()

    run([sys.executable, "-m", "build", "--wheel", "--outdir", str(DIST_DIR), str(ROOT)])

    if not _validate_wheel_tags():
        return 1

    print("[wheels] success: universal wheel build complete (py3-none-any)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
