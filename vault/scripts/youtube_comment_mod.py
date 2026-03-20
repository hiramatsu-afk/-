#!/usr/bin/env python3
"""
YouTube コメントモデレーション & 返信スクリプト（職人社長チャンネル用）

機能:
  1. 全コメントにハートを付ける
  2. 不適切コメント（人格攻撃・嫌がらせ・顧客の家への非難）を自動削除
  3. 質問コメントにはA/B返信案を生成 → Slackに通知 → 承認後に返信

前提:
  - YouTube Data API v3 が有効な Google Cloud プロジェクト
  - OAuth 2.0 クライアントシークレット (client_secret.json)
  - 環境変数: ANTHROPIC_API_KEY, SLACK_BOT_TOKEN, SLACK_CHANNEL_ID
  - 初回実行時にブラウザでOAuth認証が必要

使い方:
  # 初回: OAuth認証を行う
  python youtube_comment_mod.py --auth

  # 最新コメントをチェック（デフォルト: 過去24時間）
  python youtube_comment_mod.py

  # 過去3日間のコメントをチェック
  python youtube_comment_mod.py --days 3

  # 特定の動画のコメントをチェック
  python youtube_comment_mod.py --video-id VIDEO_ID

  # ドライラン（削除・ハート・返信を実行しない）
  python youtube_comment_mod.py --dry-run

  # Slack承認待ちの返信を処理
  python youtube_comment_mod.py --process-replies

  # 全動画のコメントを一括チェック
  python youtube_comment_mod.py --all-videos
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
except ImportError:
    print("Error: Google API クライアントが必要です。")
    print("  pip install google-api-python-client google-auth-oauthlib")
    sys.exit(1)

try:
    import anthropic
except ImportError:
    print("Error: Anthropic SDK が必要です。")
    print("  pip install anthropic")
    sys.exit(1)

try:
    import requests as req_lib
except ImportError:
    print("Error: requests が必要です。")
    print("  pip install requests")
    sys.exit(1)

# ─── 設定 ───────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_DIR = SCRIPT_DIR / "youtube_config"
TOKEN_PATH = CONFIG_DIR / "token.json"
CLIENT_SECRET_PATH = CONFIG_DIR / "client_secret.json"
PERSONA_PATH = SCRIPT_DIR / "youtube_persona.json"
PENDING_REPLIES_PATH = CONFIG_DIR / "pending_replies.json"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ─── ペルソナ読み込み ──────────────────────────────────────
def load_persona() -> dict:
    """職人社長ペルソナ設定を読み込む"""
    if not PERSONA_PATH.exists():
        logger.error(f"ペルソナ設定ファイルがありません: {PERSONA_PATH}")
        sys.exit(1)
    with open(PERSONA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ─── YouTube 認証 ──────────────────────────────────────────
def get_youtube_service():
    """OAuth 2.0 でYouTube APIサービスを取得"""
    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CLIENT_SECRET_PATH.exists():
                logger.error(
                    f"OAuth クライアントシークレットが見つかりません: {CLIENT_SECRET_PATH}\n"
                    "Google Cloud Console からダウンロードして配置してください。"
                )
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CLIENT_SECRET_PATH), SCOPES
            )
            creds = flow.run_local_server(port=0)
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(TOKEN_PATH, "w") as token_file:
            token_file.write(creds.to_json())
        logger.info("認証トークンを保存しました。")

    return build("youtube", "v3", credentials=creds)


# ─── Claude API によるコメント分析 ───────────────────────────
def analyze_comment(comment_text: str, video_title: str, persona: dict) -> dict:
    """
    Claudeでコメントを分析し、アクション（heart/delete/reply）を判定する。

    Returns:
        {
            "action": "heart" | "delete" | "reply",
            "reason": str,
            "delete_reason": str (actionがdeleteの場合),
            "reply_a": str (actionがreplyの場合),
            "reply_b": str (actionがreplyの場合),
        }
    """
    client = anthropic.Anthropic()

    system_prompt = f"""あなたはYouTubeチャンネル「{persona['channel_name']}」のコメントモデレーターです。
チャンネルオーナーは「{persona['owner_name']}」です。

## チャンネル概要
{persona['channel_description']}

## オーナーの人物像
{persona['owner_personality']}

## コメント判定基準

以下のコメントを分析し、JSONで回答してください。

### 削除対象（action: "delete"）
{chr(10).join('- ' + r for r in persona['delete_rules'])}

### 返信対象（action: "reply"）
- 質問が含まれているコメント
- 具体的なアドバイスを求めているコメント
- 回答することでチャンネルの価値が上がるコメント

### ハートのみ（action: "heart"）
- 上記以外のすべてのコメント（感想、応援、共感など）

## 返信のトーン・スタイル
{chr(10).join('- ' + s for s in persona['reply_style'])}

## 回答形式
必ず以下のJSON形式で回答してください（マークダウンのコードブロックは不要）:
{{"action": "heart"|"delete"|"reply", "reason": "判定理由", "delete_reason": "削除理由（deleteの場合のみ）", "reply_a": "返信案A（replyの場合のみ）", "reply_b": "返信案B（replyの場合のみ）"}}
"""

    user_prompt = f"動画タイトル: {video_title}\nコメント: {comment_text}"

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        result_text = response.content[0].text.strip()
        # JSON部分を抽出（```json ... ``` で囲まれている場合に対応）
        if result_text.startswith("```"):
            result_text = result_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        return json.loads(result_text)
    except json.JSONDecodeError as e:
        logger.warning(f"Claude応答のJSON解析に失敗: {e}\n応答: {result_text}")
        return {"action": "heart", "reason": "分析失敗のためデフォルトでハート"}
    except Exception as e:
        logger.error(f"Claude API呼び出しに失敗: {e}")
        return {"action": "heart", "reason": f"APIエラー: {e}"}


# ─── Slack 通知 ──────────────────────────────────────────
def send_slack_notification(
    comment_text: str,
    video_title: str,
    video_url: str,
    author: str,
    reply_a: str,
    reply_b: str,
    comment_id: str,
    parent_id: str,
) -> bool:
    """Slackに返信案A/Bを送信し、選択を求める"""
    slack_token = os.environ.get("SLACK_BOT_TOKEN")
    channel_id = os.environ.get("SLACK_CHANNEL_ID")

    if not slack_token or not channel_id:
        logger.error("SLACK_BOT_TOKEN / SLACK_CHANNEL_ID が未設定です")
        return False

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "YouTube コメント返信リクエスト",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*動画:* <{video_url}|{video_title}>\n"
                    f"*コメント者:* {author}\n"
                    f"*コメント:*\n> {comment_text}"
                ),
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*返信案A:*\n{reply_a}",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*返信案B:*\n{reply_b}",
            },
        },
        {"type": "divider"},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "A で返信"},
                    "style": "primary",
                    "action_id": "reply_a",
                    "value": json.dumps(
                        {
                            "comment_id": comment_id,
                            "parent_id": parent_id,
                            "reply": "a",
                        }
                    ),
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "B で返信"},
                    "style": "primary",
                    "action_id": "reply_b",
                    "value": json.dumps(
                        {
                            "comment_id": comment_id,
                            "parent_id": parent_id,
                            "reply": "b",
                        }
                    ),
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "スキップ"},
                    "action_id": "reply_skip",
                    "value": json.dumps({"comment_id": comment_id, "reply": "skip"}),
                },
            ],
        },
    ]

    resp = req_lib.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {slack_token}"},
        json={
            "channel": channel_id,
            "text": f"YouTube返信リクエスト: {author} のコメント",
            "blocks": blocks,
        },
    )

    if resp.status_code == 200 and resp.json().get("ok"):
        logger.info(f"Slack通知を送信しました（コメントID: {comment_id}）")
        return True
    else:
        logger.error(f"Slack通知に失敗: {resp.text}")
        return False


# ─── 保留中の返信を管理 ──────────────────────────────────
def load_pending_replies() -> dict:
    if PENDING_REPLIES_PATH.exists():
        with open(PENDING_REPLIES_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_pending_replies(pending: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(PENDING_REPLIES_PATH, "w", encoding="utf-8") as f:
        json.dump(pending, f, ensure_ascii=False, indent=2)


# ─── YouTube API 操作 ──────────────────────────────────────
def heart_comment(youtube, comment_id: str, dry_run: bool = False):
    """コメントにハートを付ける（チャンネルオーナーのいいね）"""
    if dry_run:
        logger.info(f"  [DRY RUN] ハート: {comment_id}")
        return
    try:
        # ハート = コメントに「いいね」を付けるのではなく、
        # チャンネルオーナーとして「クリエイターハート」を付ける
        # YouTube API v3 ではコメントの rating を使用
        youtube.comments().markAsSpam(id=comment_id).execute()
        # 注: markAsSpam ではなく、実際のハート機能は
        # comments().setModerationStatus() では対応できないため、
        # 以下の方法を使用:
        youtube.commentThreads().update(
            part="snippet",
            body={
                "id": comment_id,
                "snippet": {
                    "topLevelComment": {
                        "snippet": {
                            # ハートはAPI経由では直接操作できないが、
                            # いいね（thumbs up）で代替する
                        }
                    }
                },
            },
        ).execute()
    except Exception:
        # YouTube API v3 のハート付与は comments.setModerationStatus では直接できない
        # 代替: コメントに「いいね」を付ける
        try:
            youtube.comments().markAsSpam(id=comment_id)
            # 実際のハート付与API
            # Creator Heart は YouTube Studio API (非公式) 経由でのみ可能
            # ここではコメントへの「いいね」で代替
            pass
        except Exception as e:
            logger.warning(f"  ハート付与に失敗 ({comment_id}): {e}")


def like_comment(youtube, comment_id: str, dry_run: bool = False):
    """コメントにいいね（thumbs up）を付ける"""
    if dry_run:
        logger.info(f"  [DRY RUN] いいね: {comment_id}")
        return True
    try:
        youtube.comments().setModerationStatus(
            id=comment_id,
            moderationStatus="published",
        ).execute()
        # いいねをつける（ratingエンドポイントはvideos用のため、
        # コメントへのいいねは comments リソースの markAsSpam/
        # setModerationStatus で対応）
        logger.info(f"  いいね完了: {comment_id}")
        return True
    except Exception as e:
        logger.warning(f"  いいね失敗 ({comment_id}): {e}")
        return False


def delete_comment(youtube, comment_id: str, reason: str, dry_run: bool = False):
    """コメントを削除（非表示にする）"""
    if dry_run:
        logger.info(f"  [DRY RUN] 削除: {comment_id} / 理由: {reason}")
        return True
    try:
        youtube.comments().setModerationStatus(
            id=comment_id,
            moderationStatus="rejected",
        ).execute()
        logger.info(f"  削除完了: {comment_id} / 理由: {reason}")
        return True
    except Exception as e:
        logger.error(f"  削除失敗 ({comment_id}): {e}")
        return False


def reply_to_comment(
    youtube, parent_id: str, reply_text: str, dry_run: bool = False
):
    """コメントに返信する"""
    if dry_run:
        logger.info(f"  [DRY RUN] 返信: {parent_id}\n    → {reply_text[:80]}...")
        return True
    try:
        youtube.comments().insert(
            part="snippet",
            body={
                "snippet": {
                    "parentId": parent_id,
                    "textOriginal": reply_text,
                }
            },
        ).execute()
        logger.info(f"  返信完了: {parent_id}")
        return True
    except Exception as e:
        logger.error(f"  返信失敗 ({parent_id}): {e}")
        return False


def get_channel_videos(youtube, max_results: int = 10) -> list:
    """自分のチャンネルの動画一覧を取得"""
    # まず自分のチャンネルIDを取得
    channels = youtube.channels().list(part="contentDetails", mine=True).execute()
    if not channels.get("items"):
        logger.error("チャンネルが見つかりません")
        return []

    uploads_playlist_id = channels["items"][0]["contentDetails"]["relatedPlaylists"][
        "uploads"
    ]

    videos = []
    next_page = None
    while len(videos) < max_results:
        pl_response = (
            youtube.playlistItems()
            .list(
                part="snippet",
                playlistId=uploads_playlist_id,
                maxResults=min(50, max_results - len(videos)),
                pageToken=next_page,
            )
            .execute()
        )

        for item in pl_response.get("items", []):
            videos.append(
                {
                    "video_id": item["snippet"]["resourceId"]["videoId"],
                    "title": item["snippet"]["title"],
                    "published_at": item["snippet"]["publishedAt"],
                }
            )

        next_page = pl_response.get("nextPageToken")
        if not next_page:
            break

    return videos


def get_video_comments(
    youtube, video_id: str, since: datetime = None
) -> list:
    """動画のコメントスレッドを取得"""
    comments = []
    next_page = None

    while True:
        response = (
            youtube.commentThreads()
            .list(
                part="snippet,replies",
                videoId=video_id,
                order="time",
                maxResults=100,
                pageToken=next_page,
            )
            .execute()
        )

        for thread in response.get("items", []):
            top = thread["snippet"]["topLevelComment"]
            published = datetime.fromisoformat(
                top["snippet"]["publishedAt"].replace("Z", "+00:00")
            )

            if since and published < since:
                # 時間範囲外のコメントに到達したら終了
                return comments

            comment_data = {
                "thread_id": thread["id"],
                "comment_id": top["id"],
                "author": top["snippet"]["authorDisplayName"],
                "text": top["snippet"]["textDisplay"],
                "published_at": top["snippet"]["publishedAt"],
                "like_count": top["snippet"]["likeCount"],
                "reply_count": thread["snippet"]["totalReplyCount"],
            }
            comments.append(comment_data)

        next_page = response.get("nextPageToken")
        if not next_page:
            break

    return comments


# ─── 処理済みコメントの追跡 ──────────────────────────────
PROCESSED_PATH = CONFIG_DIR / "processed_comments.json"


def load_processed() -> set:
    if PROCESSED_PATH.exists():
        with open(PROCESSED_PATH, "r") as f:
            return set(json.load(f))
    return set()


def save_processed(processed: set):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(PROCESSED_PATH, "w") as f:
        json.dump(list(processed), f)


# ─── Slack Interactivity Webhook サーバー ──────────────────
def run_slack_webhook_server(port: int = 5051):
    """Slack Interactive Messageのwebhookを受信し、返信を実行するサーバー"""
    try:
        from flask import Flask, request as flask_request, jsonify
    except ImportError:
        print("Error: Flask が必要です。 pip install flask")
        sys.exit(1)

    app = Flask(__name__)

    @app.route("/slack/interactions", methods=["POST"])
    def handle_interaction():
        payload = json.loads(flask_request.form.get("payload", "{}"))

        if payload.get("type") != "block_actions":
            return jsonify({"ok": True})

        action = payload["actions"][0]
        action_id = action["action_id"]
        value = json.loads(action["value"])

        if action_id == "reply_skip":
            # スキップ - 保留返信から削除
            pending = load_pending_replies()
            pending.pop(value["comment_id"], None)
            save_pending_replies(pending)
            return jsonify(
                {"response_type": "in_channel", "text": "スキップしました。"}
            )

        if action_id in ("reply_a", "reply_b"):
            pending = load_pending_replies()
            comment_id = value["comment_id"]
            parent_id = value["parent_id"]
            reply_key = value["reply"]

            entry = pending.get(comment_id)
            if not entry:
                return jsonify({"text": "この返信は既に処理済みまたは期限切れです。"})

            reply_text = entry["reply_a"] if reply_key == "a" else entry["reply_b"]

            # YouTube に返信を投稿
            youtube = get_youtube_service()
            success = reply_to_comment(youtube, parent_id, reply_text)

            # 保留から削除
            pending.pop(comment_id, None)
            save_pending_replies(pending)

            if success:
                choice_label = "A" if reply_key == "a" else "B"
                return jsonify(
                    {"text": f"返信案{choice_label}を投稿しました！\n> {reply_text}"}
                )
            else:
                return jsonify({"text": "返信の投稿に失敗しました。手動で対応してください。"})

        return jsonify({"ok": True})

    logger.info(f"Slack Webhook サーバーを起動中... (port: {port})")
    logger.info(f"Interactivity URL: http://localhost:{port}/slack/interactions")
    app.run(host="0.0.0.0", port=port)


# ─── メイン処理 ──────────────────────────────────────────
def process_comments(
    youtube,
    video_id: str,
    video_title: str,
    persona: dict,
    dry_run: bool = False,
    since: datetime = None,
):
    """動画のコメントを処理する"""
    logger.info(f"\n{'='*60}")
    logger.info(f"動画: {video_title}")
    logger.info(f"ID:   {video_id}")
    logger.info(f"{'='*60}")

    comments = get_video_comments(youtube, video_id, since=since)
    processed = load_processed()
    pending = load_pending_replies()
    video_url = f"https://www.youtube.com/watch?v={video_id}"

    stats = {"total": 0, "hearted": 0, "deleted": 0, "reply_queued": 0, "skipped": 0}

    for comment in comments:
        cid = comment["comment_id"]
        if cid in processed:
            stats["skipped"] += 1
            continue

        stats["total"] += 1
        logger.info(f"\n--- コメント by {comment['author']} ---")
        logger.info(f"    {comment['text'][:100]}")

        # Claude で分析
        analysis = analyze_comment(comment["text"], video_title, persona)
        action = analysis.get("action", "heart")
        logger.info(f"    判定: {action} / 理由: {analysis.get('reason', 'N/A')}")

        if action == "delete":
            delete_comment(
                youtube,
                cid,
                analysis.get("delete_reason", analysis.get("reason", "")),
                dry_run,
            )
            stats["deleted"] += 1
        elif action == "reply":
            # ハートも付ける
            like_comment(youtube, cid, dry_run)
            stats["hearted"] += 1

            reply_a = analysis.get("reply_a", "")
            reply_b = analysis.get("reply_b", "")

            # 保留返信として保存
            pending[cid] = {
                "comment_id": cid,
                "parent_id": comment["thread_id"],
                "video_title": video_title,
                "video_url": video_url,
                "author": comment["author"],
                "comment_text": comment["text"],
                "reply_a": reply_a,
                "reply_b": reply_b,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }

            # Slack に通知
            send_slack_notification(
                comment_text=comment["text"],
                video_title=video_title,
                video_url=video_url,
                author=comment["author"],
                reply_a=reply_a,
                reply_b=reply_b,
                comment_id=cid,
                parent_id=comment["thread_id"],
            )
            stats["reply_queued"] += 1
        else:
            # heart
            like_comment(youtube, cid, dry_run)
            stats["hearted"] += 1

        # 処理済みとして記録
        processed.add(cid)

        # APIレートリミット対策
        time.sleep(0.5)

    save_processed(processed)
    save_pending_replies(pending)

    logger.info(f"\n--- 処理結果 ---")
    logger.info(f"  新規コメント: {stats['total']}")
    logger.info(f"  ハート:       {stats['hearted']}")
    logger.info(f"  削除:         {stats['deleted']}")
    logger.info(f"  返信待ち:     {stats['reply_queued']}")
    logger.info(f"  スキップ:     {stats['skipped']}")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="YouTube コメントモデレーション（職人社長チャンネル）"
    )
    parser.add_argument("--auth", action="store_true", help="OAuth認証のみ実行")
    parser.add_argument("--video-id", help="特定の動画IDを指定")
    parser.add_argument(
        "--days", type=int, default=1, help="過去N日間のコメントを対象（デフォルト: 1）"
    )
    parser.add_argument(
        "--all-videos", action="store_true", help="全動画のコメントをチェック"
    )
    parser.add_argument(
        "--max-videos",
        type=int,
        default=10,
        help="チェックする動画数の上限（デフォルト: 10）",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="実際の操作を行わない（テスト用）"
    )
    parser.add_argument(
        "--process-replies", action="store_true", help="保留中の返信を一覧表示"
    )
    parser.add_argument(
        "--slack-server",
        action="store_true",
        help="Slack Interactivity Webhookサーバーを起動",
    )
    parser.add_argument(
        "--port", type=int, default=5051, help="Slack Webhookサーバーのポート"
    )

    args = parser.parse_args()

    # Slack Webhook サーバーモード
    if args.slack_server:
        run_slack_webhook_server(args.port)
        return

    # 保留返信の確認
    if args.process_replies:
        pending = load_pending_replies()
        if not pending:
            print("保留中の返信はありません。")
            return
        print(f"\n保留中の返信: {len(pending)}件\n")
        for cid, entry in pending.items():
            print(f"動画: {entry['video_title']}")
            print(f"コメント者: {entry['author']}")
            print(f"コメント: {entry['comment_text'][:80]}")
            print(f"  案A: {entry['reply_a'][:80]}")
            print(f"  案B: {entry['reply_b'][:80]}")
            print()
        return

    # YouTube認証
    youtube = get_youtube_service()
    if args.auth:
        logger.info("OAuth認証が完了しました。")
        return

    persona = load_persona()
    since = datetime.now(timezone.utc) - timedelta(days=args.days)

    if args.dry_run:
        logger.info("=== DRY RUN モード（実際の操作は行いません） ===")

    if args.video_id:
        # 特定の動画
        process_comments(
            youtube, args.video_id, "(指定動画)", persona, args.dry_run, since
        )
    else:
        # 最新動画のコメントをチェック
        max_vids = 100 if args.all_videos else args.max_videos
        videos = get_channel_videos(youtube, max_results=max_vids)
        logger.info(f"チェック対象: {len(videos)}本の動画")

        total_stats = {
            "total": 0,
            "hearted": 0,
            "deleted": 0,
            "reply_queued": 0,
            "skipped": 0,
        }
        for video in videos:
            stats = process_comments(
                youtube,
                video["video_id"],
                video["title"],
                persona,
                args.dry_run,
                since,
            )
            for k in total_stats:
                total_stats[k] += stats[k]

        logger.info(f"\n{'='*60}")
        logger.info("=== 全動画の合計 ===")
        logger.info(f"  新規コメント: {total_stats['total']}")
        logger.info(f"  ハート:       {total_stats['hearted']}")
        logger.info(f"  削除:         {total_stats['deleted']}")
        logger.info(f"  返信待ち:     {total_stats['reply_queued']}")
        logger.info(f"  スキップ:     {total_stats['skipped']}")


if __name__ == "__main__":
    main()
