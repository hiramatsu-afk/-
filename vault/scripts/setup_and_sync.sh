#!/bin/bash
# ============================================================
# Obsidian Vault 一括セットアップスクリプト
# ============================================================
# このスクリプトをローカルマシンで実行すると、以下を自動で行います:
#   1. tl;dv API接続テスト
#   2. 過去の全ミーティングを一括取り込み
#   3. ダッシュボードで取り込み状況を確認
#   4. 検索機能の動作確認
#
# 使い方:
#   chmod +x vault/scripts/setup_and_sync.sh
#   ./vault/scripts/setup_and_sync.sh
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VAULT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "============================================================"
echo "  Obsidian Vault - Full Setup & Sync"
echo "============================================================"
echo ""

# --- Step 0: 依存パッケージ確認 ---
echo "## Step 0: Checking dependencies..."
python3 -c "import requests" 2>/dev/null || {
    echo "  Installing requests..."
    pip install requests
}
echo "  OK"
echo ""

# --- Step 1: APIキー確認 ---
echo "## Step 1: Checking API key..."
if [ -z "$TLDV_API_KEY" ]; then
    echo "  TLDV_API_KEY is not set."
    echo ""
    read -p "  Enter your tl;dv API key: " TLDV_API_KEY
    export TLDV_API_KEY
    echo ""
    echo "  Tip: Add this to your shell profile to persist:"
    echo "    export TLDV_API_KEY=\"$TLDV_API_KEY\""
    echo ""
fi
echo "  API key set (${#TLDV_API_KEY} chars)"
echo ""

# --- Step 2: 接続テスト ---
echo "## Step 2: Testing API connection..."
echo ""
python3 "$SCRIPT_DIR/tldv_sync.py" --test
echo ""

read -p "Continue with full sync? [Y/n] " CONFIRM
if [[ "$CONFIRM" =~ ^[Nn] ]]; then
    echo "Aborted."
    exit 0
fi
echo ""

# --- Step 3: 全ミーティング一括取り込み ---
echo "## Step 3: Syncing ALL meetings..."
echo ""
python3 "$SCRIPT_DIR/tldv_sync.py" --all
echo ""

# --- Step 4: ダッシュボード表示 ---
echo "## Step 4: Dashboard"
echo ""
python3 "$SCRIPT_DIR/vault_analyzer.py" --dashboard
echo ""

# --- Step 5: 検索テスト ---
echo "## Step 5: Vault Statistics"
echo ""
python3 "$SCRIPT_DIR/vault_analyzer.py" --stats
echo ""

echo "============================================================"
echo "  Setup complete!"
echo ""
echo "  Quick commands:"
echo "    python3 $SCRIPT_DIR/vault_analyzer.py --dashboard"
echo "    python3 $SCRIPT_DIR/vault_analyzer.py --search \"keyword\""
echo "    python3 $SCRIPT_DIR/vault_analyzer.py --attendee \"name\""
echo "    python3 $SCRIPT_DIR/vault_analyzer.py --action-items"
echo "    python3 $SCRIPT_DIR/tldv_sync.py --days 1"
echo "============================================================"
