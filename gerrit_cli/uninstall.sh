#!/bin/bash
#
# Uninstallation script for gerrit CLI tool
#

set -e  # Exit on error

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "================================================"
echo "Uninstalling Gerrit CLI Tool"
echo "================================================"
echo ""

# Try to find a suitable Python version
PYTHON_CMD=""
for py_version in python3.11 python3.10 python3.9 python3; do
    if command -v $py_version &> /dev/null; then
        PYTHON_CMD=$py_version
        break
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo -e "${RED}Error: Python 3 is not available${NC}"
    exit 1
fi

# Remove both old and new package names
for pkg in gerrit-cli gerrit-comments; do
    if $PYTHON_CMD -m pip show $pkg &> /dev/null; then
        echo "Removing $pkg..."
        $PYTHON_CMD -m pip uninstall $pkg -y
    fi
done

echo ""
echo -e "${GREEN}================================================${NC}"
echo -e "${GREEN}Uninstallation Complete!${NC}"
echo -e "${GREEN}================================================${NC}"
echo ""

# Verify uninstallation
if command -v gerrit &> /dev/null || command -v gerrit-comments &> /dev/null; then
    echo -e "${RED}⚠ Command still available in PATH (may need to restart shell)${NC}"
else
    echo -e "${GREEN}✓ Uninstallation verified successfully${NC}"
fi
