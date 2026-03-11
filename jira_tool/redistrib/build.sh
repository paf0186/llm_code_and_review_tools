#!/usr/bin/env bash
# Build jira-tool.zip redistributable
#
# Usage: ./redistrib/build.sh [output-path]
#   output-path defaults to ~/jira-tool.zip
#
# What it does:
#   1. Builds the wheel from jira_tool/
#   2. Packages it with INSTALL.md and CLAUDE.md into a zip
#
# Run from the jira_tool/ directory:
#   cd /path/to/llm_code_and_review_tools/jira_tool
#   ./redistrib/build.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JIRA_TOOL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
OUTPUT="${1:-${HOME}/jira-tool.zip}"

echo "Building jira-tool redistributable..."
echo "  Source: ${JIRA_TOOL_DIR}"
echo "  Output: ${OUTPUT}"
echo ""

# Build the wheel
cd "${JIRA_TOOL_DIR}"
echo "==> Building wheel..."
if command -v uvx &>/dev/null; then
    uvx --from build pyproject-build --wheel --outdir /tmp/jira-tool-build-$$/ .
else
    # Fallback: use a throwaway venv so we don't depend on build being
    # installed in any particular Python version
    VENV="/tmp/jira-tool-build-venv-$$"
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install build -q
    "$VENV/bin/python" -m build --wheel --outdir /tmp/jira-tool-build-$$/ .
    rm -rf "$VENV"
fi
WHEEL="$(ls /tmp/jira-tool-build-$$/jira_tool-*.whl | head -1)"
echo "    Built: $(basename "${WHEEL}")"

# Stage the zip contents
STAGE="/tmp/jira-tool-stage-$$"
mkdir -p "${STAGE}/jira-tool"

cp "${WHEEL}"                         "${STAGE}/jira-tool/"
cp "${SCRIPT_DIR}/INSTALL.md"         "${STAGE}/jira-tool/"
cp "${SCRIPT_DIR}/CLAUDE.md"          "${STAGE}/jira-tool/"

# Also copy the wheel to the jira_tool parent for standalone installs
cp "${WHEEL}" "${JIRA_TOOL_DIR}/../$(basename "${WHEEL}")"
echo "    Copied wheel to $(basename "${JIRA_TOOL_DIR}")/../$(basename "${WHEEL}")"

# Pack the zip
rm -f "${OUTPUT}"
cd "${STAGE}"
zip -r "${OUTPUT}" jira-tool/
echo ""
echo "==> Done: ${OUTPUT}"
unzip -l "${OUTPUT}"

# Cleanup
rm -rf "/tmp/jira-tool-build-$$" "/tmp/jira-tool-stage-$$"
