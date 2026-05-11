#!/usr/bin/env python3
"""
tl;dv Webhook受信サーバー + 自動化オーケストレーター

このサーバー1つで以下を自動化:
  1. tl;dvからのWebhook受信 → 議事録を自動保存
  2. 議事録保存後 → ダッシュボードを自動再生成
  3. 毎週月曜9時 → 週次レビューノートを自動生成
  4. 毎日深夜2時 → tl;dvの取りこぼし分を補完同期

セットアップ:
  pip install requests flask
  TLDV_API_KEY=xxx python tldv_webhook_server.py

  別ターミナルで:
  ngrok http 5050

  tl;dv Settings > Webhooks で以下を登録:
    Event:        TranscriptReady
    Endpoint URL: https://<ngrok-url>/webhook/tldv

オプション:
  --port 5050          サーバーポート
  --no-scheduler       内蔵スケジューラを無効化
  --no-auto-dashboard  ダッシュボード自動更新を無効化
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

try:
    from flask import Flask, request, jsonify
except ImportError:
    print("Error: Flask is required. Install with: pip install flask")
    sys.exit(1)

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from tldv_sync import TldvClient, sync_meeting, load_sync_state, save_sync_state

VAULT_ROOT = SCRIPT_DIR.parent
LOG_DIR = VAULT_ROOT / "scripts" / ".logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / "webhook_server.log", encoding="utf-8"),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
config = {"auto_dashboard": True}


def regenerate_dashboard():
    """ダッシュボードHTMLを再生成"""
    try:
        result = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "generate_dashboard.py")],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0:
            logger.info("Dashboard regenerated successfully")
        else:
            logger.error(f"Dashboard generation failed: {result.stderr}")
    except Exception as e:
        logger.error(f"Dashboard regeneration error: {e}")


def run_weekly_review():
    """週次レビューノートを生成"""
    try:
        result = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "weekly_review.py")],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0:
            logger.info(f"Weekly review generated: {result.stdout.strip()}")
            if config["auto_dashboard"]:
                regenerate_dashboard()
        else:
            logger.error(f"Weekly review failed: {result.stderr}")
    except Exception as e:
        logger.error(f"Weekly review error: {e}")


def run_catchup_sync():
    """過去24時間分の補完同期"""
    api_key = os.environ.get("TLDV_API_KEY")
    if not api_key:
        logger.warning("Skipping catchup sync (no API key)")
        return
    try:
        result = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "tldv_sync.py"), "--days", "1"],
            capture_output=True, text=True, timeout=300,
            env={**os.environ, "TLDV_API_KEY": api_key}
        )
        if result.returncode == 0:
            logger.info(f"Catchup sync completed: {result.stdout.strip()[:200]}")
            if config["auto_dashboard"]:
                regenerate_dashboard()
        else:
            logger.error(f"Catchup sync failed: {result.stderr}")
    except Exception as e:
        logger.error(f"Catchup sync error: {e}")


class Scheduler(threading.Thread):
    """シンプルな内蔵スケジューラ"""

    def __init__(self):
        super().__init__(daemon=True)
        self.stop_event = threading.Event()
        self.last_weekly = None
        self.last_catchup = None

    def run(self):
        logger.info("Scheduler started")
        while not self.stop_event.is_set():
            now = datetime.now()

            # 毎週月曜9時に週次レビュー
            if now.weekday() == 0 and now.hour == 9:
                key = now.strftime("%Y-W%W")
                if self.last_weekly != key:
                    logger.info("Triggering weekly review")
                    run_weekly_review()
                    self.last_weekly = key

            # 毎日深夜2時に補完同期
            if now.hour == 2:
                key = now.strftime("%Y-%m-%d")
                if self.last_catchup != key:
                    logger.info("Triggering catchup sync")
                    run_catchup_sync()
                    self.last_catchup = key

            self.stop_event.wait(60)

    def stop(self):
        self.stop_event.set()


@app.route("/webhook/tldv", methods=["POST"])
def handle_tldv_webhook():
    api_key = os.environ.get("TLDV_API_KEY")
    if not api_key:
        logger.error("TLDV_API_KEY not set")
        return jsonify({"error": "Server misconfigured"}), 500

    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"error": "Invalid payload"}), 400

    event_type = payload.get("event", payload.get("type", "unknown"))
    logger.info(f"Received webhook: {event_type}")

    if event_type in ("TranscriptReady", "transcript_ready", "transcript.ready"):
        meeting_data = payload.get("meeting", payload.get("data", payload))
        meeting_id = meeting_data.get("id", meeting_data.get("meetingId", ""))

        if not meeting_id:
            logger.warning("No meeting ID in webhook payload")
            return jsonify({"error": "No meeting ID"}), 400

        try:
            client = TldvClient(api_key)
            meeting = client.get_meeting(meeting_id)
            result = sync_meeting(client, meeting)

            if result:
                state = load_sync_state()
                if meeting_id not in state["synced_ids"]:
                    state["synced_ids"].append(meeting_id)
                state["last_sync"] = datetime.now().isoformat()
                save_sync_state(state)
                logger.info(f"Meeting saved: {result.name}")

                if config["auto_dashboard"]:
                    threading.Thread(target=regenerate_dashboard, daemon=True).start()

                return jsonify({"status": "saved", "file": str(result)}), 200
        except Exception as e:
            logger.exception(f"Error processing meeting {meeting_id}")
            return jsonify({"error": str(e)}), 500

    elif event_type in ("MeetingReady", "meeting_ready", "meeting.ready"):
        logger.info("Meeting ready - waiting for transcript")
        return jsonify({"status": "acknowledged"}), 200

    return jsonify({"status": "ignored", "event": event_type}), 200


@app.route("/health", methods=["GET"])
def health():
    state = load_sync_state()
    return jsonify({
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "synced_meetings": len(state.get("synced_ids", [])),
        "last_sync": state.get("last_sync"),
        "auto_dashboard": config["auto_dashboard"],
    }), 200


@app.route("/trigger/dashboard", methods=["POST"])
def trigger_dashboard():
    threading.Thread(target=regenerate_dashboard, daemon=True).start()
    return jsonify({"status": "triggered"}), 200


@app.route("/trigger/weekly-review", methods=["POST"])
def trigger_weekly():
    threading.Thread(target=run_weekly_review, daemon=True).start()
    return jsonify({"status": "triggered"}), 200


@app.route("/trigger/sync", methods=["POST"])
def trigger_sync():
    threading.Thread(target=run_catchup_sync, daemon=True).start()
    return jsonify({"status": "triggered"}), 200


def main():
    parser = argparse.ArgumentParser(description="tl;dv Webhook + Automation Server")
    parser.add_argument("--port", type=int, default=5050)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--no-scheduler", action="store_true",
                        help="Disable built-in scheduler")
    parser.add_argument("--no-auto-dashboard", action="store_true",
                        help="Disable automatic dashboard regeneration")
    args = parser.parse_args()

    config["auto_dashboard"] = not args.no_auto_dashboard

    if not os.environ.get("TLDV_API_KEY"):
        logger.warning("TLDV_API_KEY not set - webhooks will fail")

    if not args.no_scheduler:
        scheduler = Scheduler()
        scheduler.start()
        logger.info("Built-in scheduler enabled")
        logger.info("  - Weekly review: Mondays 9:00")
        logger.info("  - Catchup sync:  Daily 2:00")

    logger.info(f"Server starting on {args.host}:{args.port}")
    logger.info(f"  Webhook:         POST /webhook/tldv")
    logger.info(f"  Health:          GET  /health")
    logger.info(f"  Manual triggers: POST /trigger/{{dashboard,weekly-review,sync}}")
    logger.info(f"  Auto dashboard:  {config['auto_dashboard']}")

    app.run(host=args.host, port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
