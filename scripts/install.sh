#!/usr/bin/env bash
#
# MU Install Script
# Usage: curl -sSL https://raw.githubusercontent.com/0ximu/mu/main/scripts/install.sh | sh
#
# This script downloads and installs the latest MU binary for your platform.

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
GITHUB_REPO="0ximu/mu"
INSTALL_DIR="${MU_INSTALL_DIR:-$HOME/.local/bin}"

# Print colored message
info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1" >&2
    exit 1
}

# Detect OS
detect_os() {
    case "$(uname -s)" in
        Linux*)     echo "linux" ;;
        Darwin*)    echo "macos" ;;
        CYGWIN*|MINGW*|MSYS*) echo "windows" ;;
        *)          error "Unsupported operating system: $(uname -s)" ;;
    esac
}

# Detect architecture
detect_arch() {
    case "$(uname -m)" in
        x86_64|amd64)   echo "x86_64" ;;
        aarch64|arm64)  echo "arm64" ;;
        *)              error "Unsupported architecture: $(uname -m)" ;;
    esac
}

# Get artifact name for platform
get_artifact_name() {
    local os="$1"
    local arch="$2"

    case "${os}-${arch}" in
        linux-x86_64)   echo "mu-linux-x86_64" ;;
        macos-x86_64)   echo "mu-macos-x86_64" ;;
        macos-arm64)    echo "mu-macos-arm64" ;;
        windows-x86_64) echo "mu-windows-x86_64.exe" ;;
        *)              error "Unsupported platform: ${os}-${arch}" ;;
    esac
}

# Get latest release version
get_latest_version() {
    local url="https://api.github.com/repos/${GITHUB_REPO}/releases/latest"

    if command -v curl &> /dev/null; then
        curl -sSL "$url" | grep '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/'
    elif command -v wget &> /dev/null; then
        wget -qO- "$url" | grep '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/'
    else
        error "Neither curl nor wget found. Please install one of them."
    fi
}

# Download file
download() {
    local url="$1"
    local output="$2"

    info "Downloading from $url"

    if command -v curl &> /dev/null; then
        curl -fsSL -o "$output" "$url"
    elif command -v wget &> /dev/null; then
        wget -q -O "$output" "$url"
    else
        error "Neither curl nor wget found. Please install one of them."
    fi
}

# Verify checksum
verify_checksum() {
    local file="$1"
    local checksum_file="$2"

    if [ ! -f "$checksum_file" ]; then
        warn "Checksum file not found, skipping verification"
        return 0
    fi

    info "Verifying checksum..."

    local expected_hash
    expected_hash=$(cat "$checksum_file" | awk '{print $1}')

    local actual_hash
    if command -v shasum &> /dev/null; then
        actual_hash=$(shasum -a 256 "$file" | awk '{print $1}')
    elif command -v sha256sum &> /dev/null; then
        actual_hash=$(sha256sum "$file" | awk '{print $1}')
    else
        warn "Neither shasum nor sha256sum found, skipping verification"
        return 0
    fi

    if [ "$expected_hash" != "$actual_hash" ]; then
        error "Checksum verification failed!
Expected: $expected_hash
Actual:   $actual_hash"
    fi

    success "Checksum verified"
}

# Main installation
main() {
    echo ""
    echo "  __  __ _   _"
    echo " |  \/  | | | |"
    echo " | |\/| | | | |"
    echo " | |  | | |_| |"
    echo " |_|  |_|\___/"
    echo ""
    echo "MU Installer - Machine Understanding for Codebases"
    echo ""

    # Detect platform
    local os
    os=$(detect_os)
    local arch
    arch=$(detect_arch)
    local artifact
    artifact=$(get_artifact_name "$os" "$arch")

    info "Detected platform: $os-$arch"

    # Get latest version
    info "Fetching latest release..."
    local version
    version=$(get_latest_version)

    if [ -z "$version" ]; then
        error "Could not determine latest version. Check your network connection."
    fi

    info "Latest version: $version"

    # Create temp directory
    local tmp_dir
    tmp_dir=$(mktemp -d)
    trap "rm -rf $tmp_dir" EXIT

    # Download binary
    local download_url="https://github.com/${GITHUB_REPO}/releases/download/${version}/${artifact}"
    local binary_path="${tmp_dir}/${artifact}"
    download "$download_url" "$binary_path"

    # Download and verify checksum
    local checksum_url="${download_url}.sha256"
    local checksum_path="${tmp_dir}/${artifact}.sha256"
    download "$checksum_url" "$checksum_path" 2>/dev/null || true
    verify_checksum "$binary_path" "$checksum_path"

    # Create install directory
    mkdir -p "$INSTALL_DIR"

    # Install binary
    local install_path="${INSTALL_DIR}/mu"
    if [ "$os" = "windows" ]; then
        install_path="${INSTALL_DIR}/mu.exe"
    fi

    info "Installing to $install_path"
    cp "$binary_path" "$install_path"
    chmod +x "$install_path"

    success "MU $version installed successfully!"
    echo ""

    # Check if install dir is in PATH
    if [[ ":$PATH:" != *":$INSTALL_DIR:"* ]]; then
        warn "$INSTALL_DIR is not in your PATH"
        echo ""
        echo "Add it to your shell configuration:"
        echo ""
        echo "  # For bash/zsh:"
        echo "  export PATH=\"\$PATH:$INSTALL_DIR\""
        echo ""
        echo "  # For fish:"
        echo "  fish_add_path $INSTALL_DIR"
        echo ""
    fi

    # Verify installation
    if command -v "$install_path" &> /dev/null; then
        echo "Run 'mu --help' to get started!"
    fi

    echo ""
    echo "Documentation: https://github.com/${GITHUB_REPO}"
    echo ""
}

# Run main
main "$@"
