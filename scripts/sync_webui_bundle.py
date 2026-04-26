from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT / "frontend"
FRONTEND_DIST = FRONTEND_DIR / "dist"
TARGET_WEBUI_DIR = ROOT / "backend" / "app" / "webui"


def _resolve_npm() -> str:
    for candidate in ("npm", "npm.cmd"):
        path = shutil.which(candidate)
        if path:
            return path
    raise RuntimeError("npm executable not found in PATH (tried: npm, npm.cmd)")


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print(f"[bundle] run: {' '.join(cmd)}")
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)


def main() -> int:
    npm = _resolve_npm()
    run([npm, "run", "build"], cwd=FRONTEND_DIR)

    TARGET_WEBUI_DIR.mkdir(parents=True, exist_ok=True)
    for child in TARGET_WEBUI_DIR.iterdir():
        if child.name == ".gitkeep":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()

    if not FRONTEND_DIST.is_dir():
        print(f"[bundle] frontend dist missing: {FRONTEND_DIST}", file=sys.stderr)
        return 1

    for child in FRONTEND_DIST.iterdir():
        destination = TARGET_WEBUI_DIR / child.name
        if child.is_dir():
            shutil.copytree(child, destination)
        else:
            shutil.copy2(child, destination)

    print(f"[bundle] copied {FRONTEND_DIST} -> {TARGET_WEBUI_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
