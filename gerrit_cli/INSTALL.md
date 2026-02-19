# Installation Guide

## Quick Install

To install the `gerrit-comments` tool:

```bash
cd /shared/llm_code_and_review_tools/gerrit_comments
./install.sh
```

This will install the tool and make the `gerrit-comments` command available in your PATH.

## Requirements

- Python 3.9 or higher
- pip (Python package installer)

## Installation Methods

### Method 1: Using the install script (Recommended)

```bash
./install.sh
```

The script will:
- Detect if `uv` is available (faster) or use `pip`
- Install the package in editable mode
- Verify the installation
- Show example commands

### Method 2: Manual installation with uv

```bash
uv pip install -e .
```

### Method 3: Manual installation with pip

```bash
pip install -e .
```

## Uninstallation

```bash
./uninstall.sh
```

Or manually:

```bash
pip uninstall gerrit-comments
```

## Verification

After installation, verify it works:

```bash
gerrit-comments --help
```

You should see the help text with all available commands.

## Configuration

The tool looks for credentials in this priority order:

1. **Environment variables** (highest priority)
2. **.env file** (recommended for persistent configuration)
3. **Hardcoded defaults** (fallback)

### Option 1: Using .env file (Recommended)

The install script automatically installs the `.env` file if present in the source directory.

After installation, the file will be located at:
- User install: `~/.config/gerrit-comments/.env`
- Root install: `/etc/gerrit-comments/.env`

You can manually edit this file to update credentials:
```bash
# User install
nano ~/.config/gerrit-comments/.env

# Root install (requires sudo)
sudo nano /etc/gerrit-comments/.env
```

### Option 2: Using environment variables

Set up your Gerrit credentials in your shell:

```bash
export GERRIT_URL="https://review.whamcloud.com"
export GERRIT_USER="your-username"
export GERRIT_PASS="your-http-password"
```

Add these to your `~/.bashrc` or `~/.zshrc` to make them permanent.

## Documentation

- Quick reference: [SKILLS.md](SKILLS.md) - Agent skill description with command examples
- Full documentation: [README.md](README.md) - Complete API and usage guide

## Troubleshooting

### Command not found after installation

If `gerrit-comments` is not found after installation, your Python scripts directory may not be in PATH.

For user installs (pip without sudo):
```bash
export PATH="$HOME/.local/bin:$PATH"
```

Add this to your `~/.bashrc` or `~/.zshrc` to make it permanent.

### Permission denied when running install.sh

Make the script executable:
```bash
chmod +x install.sh
```

## Development Installation

To install with development dependencies (for running tests):

```bash
pip install -e ".[dev]"
```

Run tests:
```bash
pytest gerrit_comments/tests/ -v
```
