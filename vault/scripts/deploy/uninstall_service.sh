#!/bin/bash
# Obsidian自動化サービスのアンインストール

set -e
OS="$(uname -s)"

echo "Uninstalling Obsidian Automation Service..."

case "$OS" in
    Darwin)
        PLIST_PATH="$HOME/Library/LaunchAgents/com.user.obsidian-automation.plist"
        if [ -f "$PLIST_PATH" ]; then
            launchctl unload "$PLIST_PATH" 2>/dev/null || true
            rm -f "$PLIST_PATH"
            echo "  Removed: $PLIST_PATH"
        else
            echo "  Not installed."
        fi
        ;;
    Linux)
        systemctl --user stop obsidian-automation.service 2>/dev/null || true
        systemctl --user disable obsidian-automation.service 2>/dev/null || true
        SERVICE_PATH="$HOME/.config/systemd/user/obsidian-automation.service"
        if [ -f "$SERVICE_PATH" ]; then
            rm -f "$SERVICE_PATH"
            systemctl --user daemon-reload
            echo "  Removed: $SERVICE_PATH"
        else
            echo "  Not installed."
        fi
        ;;
    *)
        echo "Unsupported OS: $OS"
        exit 1
        ;;
esac

echo "Uninstall complete."
