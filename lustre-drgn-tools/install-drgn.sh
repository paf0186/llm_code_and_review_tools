#!/bin/bash
# Install drgn for Lustre vmcore analysis.
# Supports: Rocky/RHEL 8+, Ubuntu 20.04+, macOS (limited).
# Architectures: x86_64, aarch64/arm64.
#
# Usage:
#   ./install-drgn.sh          # install drgn + this package
#   ./install-drgn.sh --deps   # install only system dependencies
#   ./install-drgn.sh --check  # verify installation

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Detect platform ──────────────────────────────────────────

detect_os() {
	if [[ -f /etc/os-release ]]; then
		source /etc/os-release
		case "$ID" in
			rocky|rhel|centos|almalinux|ol)
				echo "rhel"
				;;
			ubuntu|debian)
				echo "debian"
				;;
			*)
				echo "unknown"
				;;
		esac
	elif [[ "$(uname -s)" == "Darwin" ]]; then
		echo "macos"
	else
		echo "unknown"
	fi
}

detect_arch() {
	local arch
	arch="$(uname -m)"
	case "$arch" in
		x86_64|amd64)
			echo "x86_64"
			;;
		aarch64|arm64)
			echo "aarch64"
			;;
		*)
			echo "$arch"
			;;
	esac
}

OS="$(detect_os)"
ARCH="$(detect_arch)"

echo "Platform: $OS / $ARCH"

# ── Install system dependencies ──────────────────────────────

install_deps_rhel() {
	echo "Installing dependencies for RHEL/Rocky..."

	# drgn needs: elfutils-devel, libdw, python3-devel
	# Build from source needs: gcc, make, autoconf, automake,
	#   libtool, pkg-config
	local pkgs=(
		python3-devel
		python3-pip
		elfutils-devel
		elfutils-libelf-devel
		gcc
		make
		autoconf
		automake
		libtool
		pkgconfig
	)

	# On RHEL 8, need to enable powertools/crb for some deps
	if [[ -f /etc/os-release ]]; then
		source /etc/os-release
		local ver="${VERSION_ID%%.*}"
		if [[ "$ver" == "8" ]]; then
			sudo dnf install -y epel-release 2>/dev/null || true
			sudo dnf config-manager --set-enabled \
				powertools 2>/dev/null || \
			sudo dnf config-manager --set-enabled \
				crb 2>/dev/null || true
		elif [[ "$ver" == "9" ]]; then
			sudo dnf install -y epel-release 2>/dev/null || true
			sudo dnf config-manager --set-enabled \
				crb 2>/dev/null || true
		fi
	fi

	sudo dnf install -y "${pkgs[@]}"
}

install_deps_debian() {
	echo "Installing dependencies for Ubuntu/Debian..."

	local pkgs=(
		python3-dev
		python3-pip
		python3-venv
		libelf-dev
		libdw-dev
		gcc
		make
		autoconf
		automake
		libtool
		pkg-config
	)

	sudo apt-get update
	sudo apt-get install -y "${pkgs[@]}"
}

install_deps_macos() {
	echo "Installing dependencies for macOS..."
	echo "Note: drgn on macOS can only analyze vmcores"
	echo "copied from Linux systems, not local crashes."

	# Need Homebrew
	if ! command -v brew &>/dev/null; then
		echo "Error: Homebrew required. Install from https://brew.sh"
		exit 1
	fi

	brew install python3 elfutils pkg-config || true
}

install_deps() {
	case "$OS" in
		rhel)   install_deps_rhel ;;
		debian) install_deps_debian ;;
		macos)  install_deps_macos ;;
		*)
			echo "Unsupported OS. Install manually:"
			echo "  - Python 3.8+, pip"
			echo "  - elfutils-devel / libdw-dev"
			echo "  - gcc, make"
			exit 1
			;;
	esac
}

# ── Install drgn ─────────────────────────────────────────────

install_drgn() {
	echo "Installing drgn..."

	# Try pip install first (works on most platforms)
	if pip3 install drgn 2>/dev/null; then
		echo "drgn installed via pip"
		return 0
	fi

	# If pip fails (common on RHEL 8 due to old pip/setuptools),
	# try with --user flag
	if pip3 install --user drgn 2>/dev/null; then
		echo "drgn installed via pip --user"
		return 0
	fi

	# Build from source as last resort
	echo "pip install failed, building drgn from source..."
	local tmpdir
	tmpdir="$(mktemp -d)"
	trap "rm -rf $tmpdir" EXIT

	cd "$tmpdir"
	git clone https://github.com/osandov/drgn.git
	cd drgn

	# drgn uses meson since v0.0.26+, fall back to setup.py
	if [[ -f meson.build ]]; then
		pip3 install meson ninja
		pip3 install .
	elif [[ -f setup.py ]]; then
		python3 setup.py install --user
	else
		echo "Error: cannot determine drgn build system"
		exit 1
	fi

	cd /
	echo "drgn built and installed from source"
}

# ── Install this package ─────────────────────────────────────

install_tools() {
	echo "Installing lustre-drgn-tools..."
	cd "$SCRIPT_DIR"
	pip3 install -e . 2>/dev/null || \
		pip3 install --user -e . 2>/dev/null || \
		echo "Warning: pip install failed, scripts usable directly"
}

# ── Verify installation ──────────────────────────────────────

check_install() {
	echo "Checking drgn installation..."

	if ! python3 -c "import drgn; print(f'drgn {drgn.__version__}')" \
		2>/dev/null; then
		echo "FAIL: drgn not importable"
		return 1
	fi

	# Check cross-arch support
	echo -n "Cross-arch support: "
	if python3 -c "
import drgn
p = drgn.Program()
print('available')
" 2>/dev/null; then
		:
	else
		echo "limited"
	fi

	# Check lustre_helpers
	if python3 -c "
import sys, os
sys.path.insert(0, '$SCRIPT_DIR')
import lustre_helpers
print('lustre_helpers: OK')
" 2>/dev/null; then
		:
	else
		echo "Warning: lustre_helpers not importable from $SCRIPT_DIR"
	fi

	echo "Architecture: $ARCH"
	echo "Platform: $OS"
	echo ""
	echo "Ready. Usage:"
	echo "  python3 $SCRIPT_DIR/lustre_analyze.py \\"
	echo "    --vmcore <path> --vmlinux <path> \\"
	echo "    --mod-dir <lustre_ko_dir> --pretty all"
}

# ── Main ─────────────────────────────────────────────────────

case "${1:-install}" in
	--deps)
		install_deps
		;;
	--check)
		check_install
		;;
	install|"")
		install_deps
		install_drgn
		install_tools
		echo ""
		check_install
		;;
	*)
		echo "Usage: $0 [--deps|--check|install]"
		exit 1
		;;
esac
