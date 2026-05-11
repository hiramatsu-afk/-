#!/bin/bash
# ============================================================
# Obsidian自動化サーバーをOSサービスとして常駐化するインストーラ
#
# macOS:   launchd (LaunchAgent) として登録
# Linux:   systemd user service として登録
#
# 使い方:
#   chmod +x install_service.sh
#   ./install_service.sh
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VAULT_PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
OS="$(uname -s)"

echo "============================================================"
echo "  Obsidian Automation Service Installer"
echo "============================================================"
echo "  Project root: $VAULT_PROJECT_ROOT"
echo "  OS:           $OS"
echo ""

# Python実行パス取得
PYTHON_PATH="$(command -v python3)"
if [ -z "$PYTHON_PATH" ]; then
    echo "Error: python3 not found in PATH"
    exit 1
fi
echo "  Python:       $PYTHON_PATH"

# 依存パッケージ確認
echo ""
echo "## Installing dependencies..."
"$PYTHON_PATH" -m pip install --user -q requests flask
echo "  OK"

# APIキー取得
echo ""
if [ -z "$TLDV_API_KEY" ]; then
    read -p "  Enter your TLDV_API_KEY: " TLDV_API_KEY
fi
if [ -z "$TLDV_API_KEY" ]; then
    echo "Error: TLDV_API_KEY required"
    exit 1
fi

# プレースホルダ置換ヘルパー
render_template() {
    local template="$1"
    local output="$2"
    sed -e "s|{{VAULT_ROOT}}|${VAULT_PROJECT_ROOT}|g" \
        -e "s|{{PYTHON_PATH}}|${PYTHON_PATH}|g" \
        -e "s|{{TLDV_API_KEY}}|${TLDV_API_KEY}|g" \
        "$template" > "$output"
}

mkdir -p "$VAULT_PROJECT_ROOT/vault/scripts/.logs"

case "$OS" in
    Darwin)
        # macOS - launchd
        PLIST_DIR="$HOME/Library/LaunchAgents"
        PLIST_PATH="$PLIST_DIR/com.user.obsidian-automation.plist"
        mkdir -p "$PLIST_DIR"

        echo ""
        echo "## Installing launchd service..."
        render_template "$SCRIPT_DIR/com.user.obsidian-automation.plist.template" "$PLIST_PATH"
        echo "  Installed: $PLIST_PATH"

        # 既存サービスがあればアンロード
        launchctl unload "$PLIST_PATH" 2>/dev/null || true
        launchctl load "$PLIST_PATH"
        echo "  Service loaded"

        echo ""
        echo "## Status:"
        launchctl list | grep obsidian-automation || echo "  (not yet running)"

        echo ""
        echo "## Service management commands:"
        echo "  Start:    launchctl load $PLIST_PATH"
        echo "  Stop:     launchctl unload $PLIST_PATH"
        echo "  Logs:     tail -f $VAULT_PROJECT_ROOT/vault/scripts/.logs/launchd.out.log"
        ;;

    Linux)
        # Linux - systemd user service
        SYSTEMD_DIR="$HOME/.config/systemd/user"
        SERVICE_PATH="$SYSTEMD_DIR/obsidian-automation.service"
        mkdir -p "$SYSTEMD_DIR"

        echo ""
        echo "## Installing systemd user service..."
        render_template "$SCRIPT_DIR/obsidian-automation.service.template" "$SERVICE_PATH"
        echo "  Installed: $SERVICE_PATH"

        systemctl --user daemon-reload
        systemctl --user enable obsidian-automation.service
        systemctl --user restart obsidian-automation.service
        echo "  Service started"

        # ログアウト後もサービスを維持
        if command -v loginctl >/dev/null 2>&1; then
            loginctl enable-linger "$USER" 2>/dev/null || true
        fi

        echo ""
        echo "## Status:"
        systemctl --user status obsidian-automation.service --no-pager -n 5 || true

        echo ""
        echo "## Service management commands:"
        echo "  Start:    systemctl --user start obsidian-automation"
        echo "  Stop:     systemctl --user stop obsidian-automation"
        echo "  Status:   systemctl --user status obsidian-automation"
        echo "  Logs:     journalctl --user -u obsidian-automation -f"
        ;;

    *)
        echo "Error: Unsupported OS: $OS"
        echo "Run manually: python3 $VAULT_PROJECT_ROOT/vault/scripts/tldv_webhook_server.py"
        exit 1
        ;;
esac

echo ""
echo "============================================================"
echo "  Installation complete!"
echo ""
echo "  Health check:"
echo "    curl http://localhost:5050/health"
echo ""
echo "  Expose to tl;dv (in another terminal):"
echo "    ngrok http 5050"
echo ""
echo "  Then register the ngrok URL in:"
echo "    tl;dv > Settings > Webhooks > Configure new Webhook"
echo "    Event:        TranscriptReady"
echo "    Endpoint URL: https://<ngrok-url>/webhook/tldv"
echo "============================================================"
