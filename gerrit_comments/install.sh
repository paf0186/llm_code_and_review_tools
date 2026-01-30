#!/bin/bash
#
# Installation script for gerrit-comments tool
# This script installs the gerrit-comments CLI tool so it can be used as described in SKILLS.md
#

set -e  # Exit on error

# Parse command line arguments
CLEAN_INSTALL=false
COPY_SKILLS=true  # Default to copying SKILLS.md

while [[ $# -gt 0 ]]; do
    case "$1" in
        --clean|-c)
            CLEAN_INSTALL=true
            shift
            ;;
        --no-copy-skills)
            COPY_SKILLS=false
            shift
            ;;
        --help|-h)
            # Handle help later
            break
            ;;
        *)
            shift
            ;;
    esac
done

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Show help if requested
if [[ "$1" == "--help" ]] || [[ "$1" == "-h" ]]; then
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Install the gerrit-comments CLI tool"
    echo ""
    echo "Options:"
    echo "  --clean, -c       Clean build artifacts before installing"
    echo "  --no-copy-skills  Skip copying SKILLS.md to checkout directories"
    echo "  --help, -h        Show this help message"
    echo ""
    exit 0
fi

echo "================================================"
echo "Installing Gerrit Comments Tool"
echo "================================================"
echo ""

# Clean up build artifacts if requested or if they exist with wrong permissions
if [ "$CLEAN_INSTALL" = true ] || [ -d "$SCRIPT_DIR/gerrit_comments.egg-info" ]; then
    if [ "$CLEAN_INSTALL" = true ]; then
        echo "Cleaning build artifacts (--clean flag)..."
    else
        echo "Cleaning existing build artifacts to avoid permission issues..."
    fi

    # Remove egg-info and other build artifacts
    rm -rf "$SCRIPT_DIR/gerrit_comments.egg-info" 2>/dev/null || true
    rm -rf "$SCRIPT_DIR/build" 2>/dev/null || true
    rm -rf "$SCRIPT_DIR/dist" 2>/dev/null || true
    rm -rf "$SCRIPT_DIR"/*.egg-info 2>/dev/null || true

    echo -e "${GREEN}✓ Cleaned build artifacts${NC}"
    echo ""
fi

# Try to find a suitable Python version (3.9+)
PYTHON_CMD=""
for py_version in python3.11 python3.10 python3.9 python3; do
    if command -v $py_version &> /dev/null; then
        PY_VERSION=$($py_version -c 'import sys; print(".".join(map(str, sys.version_info[:2])))' 2>/dev/null)
        PY_MAJOR=$(echo $PY_VERSION | cut -d. -f1)
        PY_MINOR=$(echo $PY_VERSION | cut -d. -f2)

        if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 9 ]; then
            PYTHON_CMD=$py_version
            echo "Found Python $PY_VERSION at $py_version"
            break
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo -e "${RED}Error: Python 3.9 or higher is not installed${NC}"
    echo "Please install Python 3.9 or higher"
    echo ""
    echo "Available Python versions:"
    ls -1 /usr/bin/python* 2>/dev/null | grep -E 'python[0-9]' || echo "  None found"
    exit 1
fi

# Check if pip is available, if not try to install it
if ! $PYTHON_CMD -m pip --version &> /dev/null; then
    echo -e "${YELLOW}pip is not available for $PYTHON_CMD, attempting to install...${NC}"
    if $PYTHON_CMD -m ensurepip --default-pip &> /dev/null; then
        echo -e "${GREEN}✓ pip installed successfully${NC}"
    else
        echo -e "${RED}Error: Failed to install pip for $PYTHON_CMD${NC}"
        echo "Please install pip manually for Python 3.9+"
        exit 1
    fi
fi

# Use pip for installation (more reliable across environments)
echo "Using pip for installation"

echo ""
echo "Installing from: $SCRIPT_DIR"
echo ""

# Determine if we can do editable install
# Non-root users on shared filesystems can't write to egg-info
EDITABLE_FLAG="-e"
INSTALL_DIR="$SCRIPT_DIR"
TEMP_DIR=""

if [ "$(id -u)" != "0" ]; then
    # Check if we can write to egg-info directory (the common failure point)
    CAN_WRITE=true
    EGG_INFO="$SCRIPT_DIR/gerrit_comments.egg-info"
    if [ -d "$EGG_INFO" ]; then
        if ! touch "$EGG_INFO/.test" 2>/dev/null; then
            CAN_WRITE=false
        else
            rm -f "$EGG_INFO/.test"
        fi
    elif ! touch "$SCRIPT_DIR/.install_test" 2>/dev/null; then
        CAN_WRITE=false
    else
        rm -f "$SCRIPT_DIR/.install_test"
    fi

    if [ "$CAN_WRITE" = false ]; then
        echo -e "${YELLOW}Non-writable directory detected${NC}"
        # Copy to temp directory for building
        TEMP_DIR=$(mktemp -d)
        echo "Copying source to $TEMP_DIR for build..."
        cp -r "$SCRIPT_DIR"/* "$TEMP_DIR/"
        rm -rf "$TEMP_DIR"/*.egg-info 2>/dev/null || true
        INSTALL_DIR="$TEMP_DIR"
        EDITABLE_FLAG=""
    fi
fi

echo "Installing gerrit-comments package..."
cd "$INSTALL_DIR"

# Ensure pip, setuptools, and wheel are up to date
echo "Updating pip and build tools..."
$PYTHON_CMD -m pip install --upgrade pip setuptools wheel

echo ""
echo "Installing package..."
if [ -n "$EDITABLE_FLAG" ]; then
    $PYTHON_CMD -m pip install -e .
else
    $PYTHON_CMD -m pip install .
fi

# Clean up temp directory if used
if [ -n "$TEMP_DIR" ] && [ -d "$TEMP_DIR" ]; then
    rm -rf "$TEMP_DIR"
fi

echo ""
echo -e "${GREEN}================================================${NC}"
echo -e "${GREEN}Installation Complete!${NC}"
echo -e "${GREEN}================================================${NC}"
echo ""

# Copy .env file if it exists in source directory
if [ -f "$SCRIPT_DIR/.env" ]; then
    echo "Found .env file in source directory"

    # Determine installation directory based on user
    if [ "$(id -u)" -eq 0 ]; then
        # Root install - use system-wide location
        CONFIG_DIR="/etc/gerrit-comments"
        echo "Installing as root - using system-wide config at $CONFIG_DIR"
    else
        # User install
        CONFIG_DIR="$HOME/.config/gerrit-comments"
        echo "Installing for user - using $CONFIG_DIR"
    fi

    # Create config directory if it doesn't exist
    mkdir -p "$CONFIG_DIR" 2>/dev/null || true

    # Copy .env file if it doesn't already exist in target location
    if [ -f "$SCRIPT_DIR/.env" ]; then
        if [ ! -f "$CONFIG_DIR/.env" ]; then
            cp "$SCRIPT_DIR/.env" "$CONFIG_DIR/.env"
            echo -e "${GREEN}✓ Installed .env configuration file to $CONFIG_DIR${NC}"
        else
            echo -e "${YELLOW}⚠ Config file already exists at $CONFIG_DIR/.env, not overwriting${NC}"
            echo "  If you want to update it, manually copy from: $SCRIPT_DIR/.env"
        fi
    else
        echo -e "${YELLOW}⚠ No .env file found in source directory${NC}"
        echo "  Credentials will use environment variables or defaults"
        echo "  To set up credentials, create ~/.config/gerrit-comments/.env"
    fi
fi

echo ""
echo -e "${GREEN}================================================${NC}"
echo -e "${GREEN}Installation Complete!${NC}"
echo -e "${GREEN}================================================${NC}"
echo ""
echo "The 'gerrit-comments' command is now available."
echo ""
echo "Configuration:"
if [ -f "$CONFIG_DIR/.env" ]; then
    echo "  ✓ Credentials installed to $CONFIG_DIR/.env"
else
    echo "  ⚠ No .env file found. Set credentials via environment variables:"
    echo "    export GERRIT_URL=https://review.whamcloud.com"
    echo "    export GERRIT_USER=your-username"
    echo "    export GERRIT_PASS=your-http-password"
fi
echo ""
echo "Try it out:"
echo "  gerrit-comments --help"
echo ""
echo "Example usage:"
echo "  gerrit-comments extract https://review.whamcloud.com/61965"
echo "  gerrit-comments review-series https://review.whamcloud.com/61965"
echo ""

# Install tab completion
COMPLETION_SCRIPT="$SCRIPT_DIR/scripts/gerrit-comments-completion.bash"
COMPLETION_LINE="source $COMPLETION_SCRIPT"
BASHRC="$HOME/.bashrc"

if [ -f "$COMPLETION_SCRIPT" ]; then
    if [ -f "$BASHRC" ]; then
        if grep -qF "$COMPLETION_SCRIPT" "$BASHRC" 2>/dev/null; then
            echo -e "${GREEN}✓ Tab completion already configured in ~/.bashrc${NC}"
        else
            echo "" >> "$BASHRC"
            echo "# gerrit-comments tab completion" >> "$BASHRC"
            echo "$COMPLETION_LINE" >> "$BASHRC"
            echo -e "${GREEN}✓ Tab completion added to ~/.bashrc${NC}"
            echo "  Run 'source ~/.bashrc' or restart your shell to enable"
        fi
    else
        echo -e "${YELLOW}⚠ ~/.bashrc not found, skipping tab completion setup${NC}"
        echo "  To enable manually, add to your shell rc file:"
        echo "    $COMPLETION_LINE"
    fi
else
    echo -e "${YELLOW}⚠ Completion script not found at $COMPLETION_SCRIPT${NC}"
fi

echo ""
echo "For full documentation, see GERRIT_COMMENTS_README.md"
echo ""

# Copy SKILLS.md to source directories if requested
if [ "$COPY_SKILLS" = true ]; then
    echo ""
    echo "================================================"
    echo "Copying SKILLS.md to Source Directories"
    echo "================================================"
    echo ""

    SKILLS_FILE="$SCRIPT_DIR/SKILLS.md"
    if [ ! -f "$SKILLS_FILE" ]; then
        echo -e "${RED}✗ SKILLS.md not found in $SCRIPT_DIR${NC}"
    else
        COPIED_COUNT=0
        FAILED_COUNT=0

        # Copy to directories under /shared/master_checkouts/
        if [ -d "/shared/master_checkouts" ]; then
            echo "Copying to /shared/master_checkouts/ directories..."
            for dir in /shared/master_checkouts/*/; do
                if [ -d "$dir" ]; then
                    TARGET="$dir/SKILLS.md"
                    if cp "$SKILLS_FILE" "$TARGET" 2>/dev/null; then
                        echo "  ✓ $(basename "$dir")"
                        COPIED_COUNT=$((COPIED_COUNT + 1))
                    else
                        echo "  ✗ $(basename "$dir") (permission denied or error)"
                        FAILED_COUNT=$((FAILED_COUNT + 1))
                    fi
                fi
            done
        fi

        # Copy to directories under /shared/ddn_checkouts/
        if [ -d "/shared/ddn_checkouts" ]; then
            echo "Copying to /shared/ddn_checkouts/ directories..."
            for dir in /shared/ddn_checkouts/*/; do
                if [ -d "$dir" ]; then
                    TARGET="$dir/SKILLS.md"
                    if cp "$SKILLS_FILE" "$TARGET" 2>/dev/null; then
                        echo "  ✓ $(basename "$dir")"
                        COPIED_COUNT=$((COPIED_COUNT + 1))
                    else
                        echo "  ✗ $(basename "$dir") (permission denied or error)"
                        FAILED_COUNT=$((FAILED_COUNT + 1))
                    fi
                fi
            done
        fi

        echo ""
        if [ $COPIED_COUNT -gt 0 ]; then
            echo -e "${GREEN}✓ Copied SKILLS.md to $COPIED_COUNT director(ies)${NC}"
        fi
        if [ $FAILED_COUNT -gt 0 ]; then
            echo -e "${YELLOW}⚠ Failed to copy to $FAILED_COUNT director(ies)${NC}"
        fi
        if [ $COPIED_COUNT -eq 0 ] && [ $FAILED_COUNT -eq 0 ]; then
            echo -e "${YELLOW}⚠ No directories found under /shared/master_checkouts/ or /shared/ddn_checkouts/${NC}"
        fi
        echo ""
    fi
fi

# Verify installation
if command -v gerrit-comments &> /dev/null; then
    echo -e "${GREEN}✓ Installation verified successfully${NC}"
    exit 0
else
    echo -e "${YELLOW}⚠ Installation completed but 'gerrit-comments' command not found in PATH${NC}"
    echo "You may need to add your Python scripts directory to PATH"
    echo "For pip user installs, try: export PATH=\"\$HOME/.local/bin:\$PATH\""
    exit 1
fi
