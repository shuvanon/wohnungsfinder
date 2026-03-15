#!/usr/bin/env bash
# setup.sh — One-command setup for Ubuntu server (Ubuntu 22.04 / 24.04)
#
# Usage:
#   chmod +x setup.sh
#   ./setup.sh
#
# What it does:
#   1. Checks Python version
#   2. Installs pip dependencies
#   3. Creates logs/ and data/ directories
#   4. Validates that settings.json has been configured
#   5. Runs the test suite
#   6. Optionally installs the systemd service

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON=python3
SERVICE_FILE="$PROJECT_DIR/wohnungsfinder.service"
SYSTEMD_DIR="/etc/systemd/system"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()    { echo -e "${GREEN}[✔]${NC} $*"; }
warning() { echo -e "${YELLOW}[!]${NC} $*"; }
error()   { echo -e "${RED}[✘]${NC} $*"; exit 1; }

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Wohnungsfinder Scraper — Server Setup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── 1. Python version check ────────────────────────────────────────────────────
read -r PYTHON_MAJOR PYTHON_MINOR PYTHON_VERSION < <(
    $PYTHON -c 'import sys; v=sys.version_info; print(v.major, v.minor, f"{v.major}.{v.minor}")'
)

if [[ $PYTHON_MAJOR -lt 3 ]] || [[ $PYTHON_MAJOR -eq 3 && $PYTHON_MINOR -lt 10 ]]; then
    error "Python 3.10+ required (found $PYTHON_VERSION). Install it with: sudo apt install python3.12"
fi
info "Python $PYTHON_VERSION found"

# ── 2. Install dependencies ────────────────────────────────────────────────────
echo ""
echo "Installing Python dependencies..."

$PYTHON -m pip install --quiet -r "$PROJECT_DIR/requirements.txt"
$PYTHON -m pip install --quiet pytest
info "Dependencies installed"

# ── 3. Create runtime directories ─────────────────────────────────────────────
mkdir -p "$PROJECT_DIR/logs" "$PROJECT_DIR/data"
info "Runtime directories ready"

# ── 4. Validate config ────────────────────────────────────────────────────────
CONFIG="$PROJECT_DIR/config/settings.json"

if [[ ! -f "$CONFIG" ]]; then
    error "config/settings.json not found. It should have been included in the project."
fi

BOT_TOKEN=$(python3 -c "import json; c=json.load(open('$CONFIG')); print(c['telegram']['bot_token'])")
CHAT_ID=$(python3 -c "import json; c=json.load(open('$CONFIG')); print(c['telegram']['chat_id'])")

if [[ "$BOT_TOKEN" == "YOUR_BOT_TOKEN_HERE" ]]; then
    warning "Telegram bot_token is not configured in config/settings.json"
    warning "The scraper will print notifications to stdout instead of Telegram."
    warning "Edit config/settings.json when ready. See README.md for instructions."
else
    info "Telegram bot_token is configured"
fi

if [[ "$CHAT_ID" == "YOUR_CHAT_ID_HERE" ]]; then
    warning "Telegram chat_id is not configured in config/settings.json"
fi

# ── 5. Run tests ───────────────────────────────────────────────────────────────
echo ""
echo "Running test suite..."
cd "$PROJECT_DIR"
if $PYTHON -m pytest tests/ -v --tb=short 2>&1; then
    info "All tests passed"
else
    error "Tests failed — fix errors above before running the scraper"
fi

# ── 6. Optional systemd install ───────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
read -r -p "Install as a systemd service for 24/7 operation? [y/N] " INSTALL_SERVICE

if [[ "${INSTALL_SERVICE,,}" == "y" ]]; then
    if [[ $EUID -ne 0 ]]; then
        error "Root required to install systemd service. Re-run with: sudo ./setup.sh"
    fi

    CURRENT_USER=$(logname 2>/dev/null || echo "$SUDO_USER")
    if [[ -z "$CURRENT_USER" ]]; then
        read -r -p "Enter the username to run the service as: " CURRENT_USER
    fi

    # Patch the service file with actual paths
    sed \
        -e "s|User=youruser|User=$CURRENT_USER|g" \
        -e "s|WorkingDirectory=.*|WorkingDirectory=$PROJECT_DIR|g" \
        -e "s|ExecStart=.*|ExecStart=$PYTHON $PROJECT_DIR/main.py|g" \
        "$SERVICE_FILE" > "$SYSTEMD_DIR/wohnungsfinder.service"

    systemctl daemon-reload
    systemctl enable wohnungsfinder
    systemctl start wohnungsfinder

    info "Service installed and started"
    info "Check status:  sudo systemctl status wohnungsfinder"
    info "Follow logs:   sudo journalctl -u wohnungsfinder -f"
else
    echo ""
    info "Skipped systemd install. To run manually:"
    echo ""
    echo "    cd $PROJECT_DIR"
    echo "    python3 main.py"
    echo ""
    echo "To run in the background:"
    echo ""
    echo "    nohup python3 main.py &"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
info "Setup complete"
echo ""
