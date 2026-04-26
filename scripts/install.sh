#!/usr/bin/env bash

set -euo pipefail

COLOR_RESET="\033[0m"
COLOR_INFO="\033[1;36m"
COLOR_WARN="\033[1;33m"
COLOR_OK="\033[1;32m"
COLOR_ERR="\033[1;31m"

info() { printf "%b[i] %s%b\n" "$COLOR_INFO" "$1" "$COLOR_RESET"; }
ok() { printf "%b[✓] %s%b\n" "$COLOR_OK" "$1" "$COLOR_RESET"; }
warn() { printf "%b[!] %s%b\n" "$COLOR_WARN" "$1" "$COLOR_RESET"; }
err() { printf "%b[x] %s%b\n" "$COLOR_ERR" "$1" "$COLOR_RESET"; }

resolve_python() {
  if command -v python3 >/dev/null 2>&1; then
    echo "python3"
    return
  fi
  if command -v python >/dev/null 2>&1; then
    echo "python"
    return
  fi
  return 1
}

check_prereqs() {
  local py_bin
  py_bin="$(resolve_python)" || {
    err "Python 3.11+ is not available in PATH."
    warn "Install Python first, then rerun this script."
    return 1
  }

  "$py_bin" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" || {
    err "Detected Python is below 3.11."
    warn "Install Python 3.11+ and rerun this script."
    return 1
  }

  "$py_bin" -m venv --help >/dev/null 2>&1 || {
    err "Python venv module is unavailable."
    warn "Install Python venv support and rerun this script."
    return 1
  }

  if [[ "$(uname -s)" == "Linux" ]]; then
    if command -v pkg-config >/dev/null 2>&1 && pkg-config --exists portaudio-2.0; then
      :
    elif [[ -f /usr/include/portaudio.h || -f /usr/local/include/portaudio.h ]]; then
      :
    elif command -v dpkg >/dev/null 2>&1 && dpkg -s portaudio19-dev >/dev/null 2>&1; then
      :
    elif command -v rpm >/dev/null 2>&1 && rpm -q portaudio-devel >/dev/null 2>&1; then
      :
    else
      err "PortAudio development package is missing (required on Linux for PyAudio build)."
      warn "Install it manually, then rerun this script."
      warn "Debian/Ubuntu: sudo apt-get install -y portaudio19-dev"
      warn "Fedora/RHEL:  sudo dnf install -y portaudio-devel"
      return 1
    fi
  fi

  echo "$py_bin"
}

choose_target_dir() {
  while true; do
    read -r -p "Use current directory as install target? [Y/n]: " use_current
    use_current="${use_current:-Y}"

    local candidate
    if [[ "$use_current" =~ ^[Yy]$ ]]; then
      candidate="$PWD"
    else
      read -r -p "Enter full path to an existing EMPTY directory: " candidate
      candidate="${candidate:-}"
    fi

    if [[ -z "$candidate" ]]; then
      warn "Path cannot be empty."
      continue
    fi

    if [[ ! -d "$candidate" ]]; then
      warn "Directory does not exist: $candidate"
      warn "Create it manually and retry."
      continue
    fi

    if find "$candidate" -mindepth 1 -maxdepth 1 | read -r _; then
      warn "Directory is not empty: $candidate"
      warn "Please choose an EMPTY directory."
      continue
    fi

    echo "$candidate"
    return
  done
}

main() {
  info "EchoNanny installer (Linux/macOS)"

  local py_bin
  py_bin="$(check_prereqs)" || exit 1
  ok "Prerequisites check passed"

  local target_dir
  target_dir="$(choose_target_dir)"
  cd "$target_dir"
  ok "Using target directory: $target_dir"

  info "Creating virtual environment (.venv)..."
  "$py_bin" -m venv .venv

  # shellcheck disable=SC1091
  source .venv/bin/activate
  ok "Virtual environment activated"

  info "Installing EchoNanny from PyPI..."
  python -m pip install --upgrade pip
  python -m pip install echonanny
  ok "EchoNanny installed"

  info "Creating .env from template..."
  echonanny init-env
  ok ".env created"

  printf "\n%bNext steps:%b\n" "$COLOR_OK" "$COLOR_RESET"
  printf "  1) Edit credentials in: %b%s/.env%b\n" "$COLOR_INFO" "$target_dir" "$COLOR_RESET"
  printf "     - INSTANCE_USER_EMAIL\n"
  printf "     - INSTANCE_USER_PASSWORD\n"
  printf "  2) Start server from this directory:\n"
  printf "     %bechonanny serve%b\n" "$COLOR_INFO" "$COLOR_RESET"
  printf "  3) Open Web UI on this PC: %bhttp://127.0.0.1:8000%b\n" "$COLOR_INFO" "$COLOR_RESET"
  printf "\n%bRemote access warning:%b\n" "$COLOR_WARN" "$COLOR_RESET"
  printf "  For access outside your local machine/network, use secure tunneling\n"
  printf "  (e.g. Cloudflare Tunnel, zrok) or proper network forwarding.\n"
  printf "  Login credentials are the values you set in .env.\n\n"
}

main "$@"
