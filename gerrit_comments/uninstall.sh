#!/bin/bash
#
# Uninstallation script for gerrit-comments tool
#

set -e  # Exit on error

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "================================================"
echo "Uninstalling Gerrit Comments Tool"
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

# Check if the package is installed
if ! $PYTHON_CMD -m pip show gerrit-comments &> /dev/null; then
    echo -e "${YELLOW}gerrit-comments is not installed${NC}"
    exit 0
fi

# Detect if uv is available
if command -v uv &> /dev/null; then
    echo "Using uv for uninstallation..."
    uv pip uninstall gerrit-comments -y
else
    echo "Using pip for uninstallation..."
    $PYTHON_CMD -m pip uninstall gerrit-comments -y
fi

echo ""
echo -e "${GREEN}================================================${NC}"
echo -e "${GREEN}Uninstallation Complete!${NC}"
echo -e "${GREEN}================================================${NC}"
echo ""

# Verify uninstallation
if command -v gerrit-comments &> /dev/null; then
    echo -e "${RED}⚠ Command still available in PATH (may need to restart shell)${NC}"
else
    echo -e "${GREEN}✓ Uninstallation verified successfully${NC}"
fi
