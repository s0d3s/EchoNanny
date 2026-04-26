from __future__ import annotations

import argparse
import ctypes
import os
import socket
import shutil
import sys
from pathlib import Path


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _runtime_project_root() -> Path:
    if _is_frozen():
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def _resolve_package_env_example() -> Path:
    local_parent = Path(__file__).resolve().parent

    candidates = [
        local_parent / ".env.example",
        local_parent / "app" / ".env.example",
    ]

    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        meipass_path = Path(meipass)
        candidates.extend([
            meipass_path / ".env.example",
            meipass_path / "app" / ".env.example",
        ])

    for candidate in candidates:
        if candidate.is_file():
            return candidate

    return candidates[0]


def _prepare_frozen_runtime_layout() -> None:
    if not _is_frozen():
        return

    root = _runtime_project_root()
    os.chdir(root)

    env_target = root / ".env"
    if env_target.exists():
        return

    src = _resolve_package_env_example()
    if not src.is_file():
        print(f"[cli] .env.example template not found in package: {src}", file=sys.stderr)
        return

    shutil.copyfile(src, env_target)
    print(f"[cli] first startup: created {env_target} from {src}")


def _enable_windows_virtual_terminal(stream: object) -> bool:
    if os.name != "nt":
        return True

    fileno = getattr(stream, "fileno", None)
    if fileno is None:
        return False

    try:
        import msvcrt

        handle = msvcrt.get_osfhandle(fileno())
        mode = ctypes.c_uint()
        kernel32 = ctypes.windll.kernel32
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)) == 0:
            return False

        ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        new_mode = mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING
        if kernel32.SetConsoleMode(handle, new_mode) == 0:
            return False
        return True
    except Exception:
        return False


def _should_use_colors() -> bool:
    no_color = os.environ.get("NO_COLOR")
    if no_color is not None:
        return False

    force_color = os.environ.get("FORCE_COLOR", "").strip().lower()
    if force_color in {"1", "true", "yes", "on"}:
        return True
    if force_color in {"0", "false", "no", "off"}:
        return False

    stderr_is_tty = bool(getattr(sys.stderr, "isatty", lambda: False)())
    stdout_is_tty = bool(getattr(sys.stdout, "isatty", lambda: False)())
    if not (stderr_is_tty or stdout_is_tty):
        return False

    if os.name == "nt":
        stderr_ok = _enable_windows_virtual_terminal(sys.stderr) if stderr_is_tty else False
        stdout_ok = _enable_windows_virtual_terminal(sys.stdout) if stdout_is_tty else False
        return stderr_ok or stdout_ok

    return True


def cmd_serve(args: argparse.Namespace) -> int:
    if args.env_file:
        env_file = Path(args.env_file).resolve()
        os.environ["ECHONANNY_ENV_FILE"] = str(env_file)

    _prepare_frozen_runtime_layout()

    # Import concrete app object so frozen builds do not rely on runtime
    # string-based module resolution like "app.main:app".
    from app.main import app as fastapi_app
    from uvicorn import run

    host = args.host
    port = int(args.port) if args.port is not None else 8000

    def _is_port_free(bind_host: str, bind_port: int) -> bool:
        probe_host = "127.0.0.1" if bind_host in {"0.0.0.0", "::"} else bind_host
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.25)
            return sock.connect_ex((probe_host, bind_port)) != 0

    def _find_next_free_port(bind_host: str, start: int, stop: int = 8100) -> int | None:
        for candidate in range(start, stop + 1):
            if _is_port_free(bind_host, candidate):
                return candidate
        return None

    # If user did not provide --port and default 8000 is busy, auto-fallback.
    if args.port is None and not _is_port_free(host, port):
        next_port = _find_next_free_port(host, 8001)
        if next_port is None:
            print("[cli] No free port found in range 8001..8100. Use --port to set a custom one.", file=sys.stderr)
            return 1
        print(f"[cli] Port 8000 is busy; switching to {next_port}.")
        port = next_port

    # If user explicitly provided a port, fail fast with clear guidance.
    if args.port is not None and not _is_port_free(host, port):
        print(f"[cli] Port {port} is already in use. Run with another port, e.g. --port {port + 1}", file=sys.stderr)
        return 1

    run(
        fastapi_app,
        host=host,
        port=port,
        reload=args.reload,
        use_colors=_should_use_colors(),
    )
    return 0


def cmd_init_env(args: argparse.Namespace) -> int:
    src = _resolve_package_env_example()
    if not src.is_file():
        print(f"[cli] .env.example template not found in package: {src}", file=sys.stderr)
        return 1

    target = _runtime_project_root() / ".env"
    if target.exists() and not args.force:
        print(f"[cli] {target} already exists. Use --force to overwrite.", file=sys.stderr)
        return 1

    shutil.copyfile(src, target)
    print(f"[cli] created {target} from {src}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="echonanny", description="EchoNanny CLI")
    sub = parser.add_subparsers(dest="command", required=False)

    serve = sub.add_parser("serve", help="Run FastAPI server")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument("--reload", action="store_true", help="Enable autoreload")
    serve.add_argument("--env-file", default="", help="Path to .env file (overrides cwd .env lookup)")
    serve.set_defaults(func=cmd_serve)

    init_env = sub.add_parser("init-env", help="Create .env in current directory from packaged .env.example")
    init_env.add_argument("--force", action="store_true", help="Overwrite existing .env")
    init_env.set_defaults(func=cmd_init_env)

    return parser


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    # For packaged EXE ergonomics: running without args should start server.
    if not argv:
        argv = ["serve"]

    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 1
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
