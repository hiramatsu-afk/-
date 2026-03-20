#!/usr/bin/env python3
"""
tl;dv Webhook受信サーバー

tl;dvのWebhookイベント（MeetingReady / TranscriptReady）を受信し、
自動的にObsidian Vaultに議事録を保存する。

前提:
  - tl;dv Business or Enterprise プラン
  - TLDV_API_KEY 環境変数にAPIキーを設定
  - ngrokなどでローカルサーバーを外部公開するか、サーバー上で稼働

セットアップ:
  1. pip install requests flask
  2. python tldv_webhook_server.py を起動（デフォルトport: 5050）
  3. ngrok http 5050 で外部URLを取得
  4. tl;dv Settings > Webhooks で以下を設定:
     - Event: TranscriptReady
     - Endpoint URL: https://<ngrok-url>/webhook/tldv

使い方:
  python tldv_webhook_server.py
  python tldv_webhook_server.py --port 8080
"""

import argparse
import json
import os
import sys
import logging
from datetime import datetime
from pathlib import Path

try:
    from flask import Flask, request, jsonify
except ImportError:
    print("Error: Flask is required. Install with: pip install flask")
    sys.exit(1)

# tldv_sync.py の機能を再利用
script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(script_dir))
from tldv_sync import TldvClient, sync_meeting, load_sync_state, save_sync_state

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@app.route("/webhook/tldv", methods=["POST"])
def handle_tldv_webhook():
    """tl;dv Webhookイベントを受信して処理"""
    api_key = os.environ.get("TLDV_API_KEY")
    if not api_key:
        logger.error("TLDV_API_KEY not set")
        return jsonify({"error": "Server misconfigured"}), 500

    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"error": "Invalid payload"}), 400

    event_type = payload.get("event", payload.get("type", "unknown"))
    logger.info(f"Received webhook event: {event_type}")
    logger.info(f"Payload: {json.dumps(payload, indent=2, ensure_ascii=False)[:1000]}")

    # TranscriptReady イベントの処理
    if event_type in ("TranscriptReady", "transcript_ready", "transcript.ready"):
        meeting_data = payload.get("meeting", payload.get("data", payload))
        meeting_id = meeting_data.get("id", meeting_data.get("meetingId", ""))

        if not meeting_id:
            logger.warning("No meeting ID in webhook payload")
            return jsonify({"error": "No meeting ID"}), 400

        try:
            client = TldvClient(api_key)
            # API から完全なミーティングデータを取得
            meeting = client.get_meeting(meeting_id)
            result = sync_meeting(client, meeting)

            if result:
                state = load_sync_state()
                state["synced_ids"].append(meeting_id)
                state["last_sync"] = datetime.now().isoformat()
                save_sync_state(state)
                logger.info(f"Meeting saved: {result}")
                return jsonify({"status": "saved", "file": str(result)}), 200
        except Exception as e:
            logger.error(f"Error processing meeting {meeting_id}: {e}")
            return jsonify({"error": str(e)}), 500

    # MeetingReady イベント（ログのみ、トランスクリプトはまだ無い）
    elif event_type in ("MeetingReady", "meeting_ready", "meeting.ready"):
        logger.info("Meeting ready event received - waiting for transcript...")
        return jsonify({"status": "acknowledged"}), 200

    return jsonify({"status": "ignored", "event": event_type}), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "timestamp": datetime.now().isoformat()}), 200


def main():
    parser = argparse.ArgumentParser(description="tl;dv Webhook Server for Obsidian")
    parser.add_argument("--port", type=int, default=5050, help="Server port (default: 5050)")
    parser.add_argument("--host", default="0.0.0.0", help="Server host (default: 0.0.0.0)")
    args = parser.parse_args()

    if not os.environ.get("TLDV_API_KEY"):
        logger.warning("TLDV_API_KEY not set - webhooks will fail until configured")

    logger.info(f"Starting tl;dv webhook server on {args.host}:{args.port}")
    logger.info("Webhook endpoint: POST /webhook/tldv")
    logger.info("Health check:     GET  /health")
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
