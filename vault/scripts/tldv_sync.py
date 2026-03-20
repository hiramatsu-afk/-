#!/usr/bin/env python3
"""
tl;dv (TLDV) からミーティング議事録を自動取得し、Obsidian Vaultに保存するスクリプト。

前提:
  - tl;dv Business or Enterprise プラン（API利用に必要）
  - API Key を環境変数 TLDV_API_KEY に設定

使い方:
  # 最新のミーティングを取得して保存
  python tldv_sync.py

  # 過去7日間のミーティングを同期
  python tldv_sync.py --days 7

  # 過去のミーティングを全件同期
  python tldv_sync.py --all

  # 特定のミーティングIDを取得
  python tldv_sync.py --meeting-id <MEETING_ID>

  # ドライラン（保存せずに内容を表示）
  python tldv_sync.py --dry-run

  # 接続テスト（APIキーの検証とミーティング数の確認）
  python tldv_sync.py --test

定期実行（cron例）:
  # 毎日朝9時に前日分を同期
  0 9 * * * TLDV_API_KEY=your_key python /path/to/tldv_sync.py --days 1
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

try:
    import requests
except ImportError:
    print("Error: requests library is required. Install with: pip install requests")
    sys.exit(1)

VAULT_ROOT = Path(__file__).resolve().parent.parent
MEETING_DIR = VAULT_ROOT / "MeetingNotes"
SYNC_STATE_FILE = VAULT_ROOT / "scripts" / ".tldv_sync_state.json"

BASE_URL = "https://pasta.tldv.io/v1alpha1"


class TldvClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "x-api-key": api_key,
            "Content-Type": "application/json",
        })

    def list_meetings(self, limit: int = 20, offset: int = 0) -> dict:
        """ミーティング一覧を取得"""
        resp = self.session.get(
            f"{BASE_URL}/meetings",
            params={"limit": limit, "offset": offset}
        )
        resp.raise_for_status()
        return resp.json()

    def list_all_meetings(self, batch_size: int = 100) -> list:
        """ページネーションで全ミーティングを取得"""
        all_meetings = []
        offset = 0
        while True:
            data = self.list_meetings(limit=batch_size, offset=offset)
            meetings = data if isinstance(data, list) else data.get("meetings", data.get("results", []))
            if not meetings:
                break
            all_meetings.extend(meetings)
            if len(meetings) < batch_size:
                break
            offset += batch_size
            print(f"  Fetched {len(all_meetings)} meetings so far...")
        return all_meetings

    def test_connection(self) -> dict:
        """API接続テスト - キーの有効性とアクセス可能なデータを確認"""
        results = {"api_key_valid": False, "meetings_accessible": False, "details": {}}
        try:
            data = self.list_meetings(limit=1)
            results["api_key_valid"] = True
            meetings = data if isinstance(data, list) else data.get("meetings", data.get("results", []))
            results["meetings_accessible"] = True
            results["details"]["first_meeting"] = meetings[0] if meetings else None
            # 全件数を推定
            all_data = self.list_meetings(limit=1, offset=0)
            total = all_data.get("total", all_data.get("count", len(meetings)))
            results["details"]["total_meetings"] = total
        except requests.exceptions.HTTPError as e:
            results["details"]["error"] = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
        except Exception as e:
            results["details"]["error"] = str(e)
        return results

    def get_meeting(self, meeting_id: str) -> dict:
        """ミーティング詳細を取得"""
        resp = self.session.get(f"{BASE_URL}/meetings/{meeting_id}")
        resp.raise_for_status()
        return resp.json()

    def get_transcript(self, meeting_id: str) -> dict:
        """トランスクリプト（文字起こし）を取得"""
        resp = self.session.get(f"{BASE_URL}/meetings/{meeting_id}/transcript")
        resp.raise_for_status()
        return resp.json()

    def get_highlights(self, meeting_id: str) -> dict:
        """ハイライト（AI要約・重要ポイント）を取得"""
        resp = self.session.get(f"{BASE_URL}/meetings/{meeting_id}/highlights")
        resp.raise_for_status()
        return resp.json()


def sanitize_filename(name: str) -> str:
    for ch in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']:
        name = name.replace(ch, '_')
    return name.strip()[:80]


def format_transcript(transcript_data) -> str:
    """トランスクリプトを読みやすいMarkdownに変換"""
    if isinstance(transcript_data, str):
        return transcript_data

    lines = []
    entries = transcript_data if isinstance(transcript_data, list) else transcript_data.get("transcript", [])

    current_speaker = None
    for entry in entries:
        speaker = entry.get("speaker", entry.get("speakerName", "Unknown"))
        text = entry.get("text", entry.get("content", ""))
        timestamp = entry.get("start", entry.get("timestamp", ""))

        if speaker != current_speaker:
            current_speaker = speaker
            if timestamp:
                minutes = int(float(timestamp)) // 60
                seconds = int(float(timestamp)) % 60
                lines.append(f"\n**{speaker}** ({minutes:02d}:{seconds:02d}):")
            else:
                lines.append(f"\n**{speaker}**:")

        lines.append(f"> {text}")

    return "\n".join(lines)


def format_highlights(highlights_data) -> str:
    """ハイライトをMarkdownに変換"""
    if isinstance(highlights_data, str):
        return highlights_data

    lines = []
    entries = highlights_data if isinstance(highlights_data, list) else highlights_data.get("highlights", [])

    for h in entries:
        title = h.get("title", h.get("label", ""))
        text = h.get("text", h.get("content", ""))
        if title:
            lines.append(f"- **{title}**: {text}")
        else:
            lines.append(f"- {text}")

    return "\n".join(lines) if lines else "(ハイライトなし)"


def build_meeting_note(meeting: dict, transcript: str, highlights: str) -> str:
    """ミーティングノートのMarkdownを生成"""
    title = meeting.get("title", meeting.get("name", "Untitled Meeting"))
    meeting_date = meeting.get("date", meeting.get("createdAt", ""))
    meeting_id = meeting.get("id", meeting.get("meetingId", ""))
    platform = meeting.get("platform", meeting.get("source", "unknown"))
    url = meeting.get("url", meeting.get("shareUrl", ""))

    # 参加者
    attendees = meeting.get("attendees", meeting.get("invitees", []))
    if isinstance(attendees, list):
        attendee_list = "\n".join(f"- {a.get('name', a) if isinstance(a, dict) else a}"
                                  for a in attendees)
    else:
        attendee_list = str(attendees)

    # 日付パース
    try:
        if meeting_date:
            dt = datetime.fromisoformat(meeting_date.replace("Z", "+00:00"))
            date_str = dt.strftime("%Y-%m-%d")
            time_str = dt.strftime("%H:%M")
        else:
            date_str = datetime.now().strftime("%Y-%m-%d")
            time_str = ""
    except (ValueError, TypeError):
        date_str = datetime.now().strftime("%Y-%m-%d")
        time_str = ""

    frontmatter = f"""---
type: meeting
date: "{date_str}"
time: "{time_str}"
platform: "{platform}"
meeting_id: "{meeting_id}"
tldv_url: "{url}"
attendees: [{', '.join(f'"{a.get("name", a) if isinstance(a, dict) else a}"' for a in attendees) if isinstance(attendees, list) else ''}]
tags: [meeting, tldv, {platform}]
status: draft
synced_at: "{datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}"
---"""

    body = f"""
# {title}

## 基本情報
- **日時**: {date_str} {time_str}
- **プラットフォーム**: {platform}
- **tl;dv リンク**: {url}

## 参加者
{attendee_list if attendee_list else '- (不明)'}

## ハイライト・要点
{highlights}

## トランスクリプト（全文）

<details>
<summary>クリックして展開</summary>

{transcript}

</details>
"""
    return frontmatter + body


def load_sync_state() -> dict:
    """前回の同期状態を読み込み"""
    if SYNC_STATE_FILE.exists():
        return json.loads(SYNC_STATE_FILE.read_text(encoding="utf-8"))
    return {"synced_ids": [], "last_sync": None}


def save_sync_state(state: dict):
    """同期状態を保存"""
    SYNC_STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False),
                                encoding="utf-8")


def sync_meeting(client: TldvClient, meeting: dict, dry_run: bool = False) -> Path | None:
    """1件のミーティングを同期"""
    meeting_id = meeting.get("id", meeting.get("meetingId", ""))
    title = meeting.get("title", meeting.get("name", "Untitled"))

    print(f"  Processing: {title} ({meeting_id})")

    # トランスクリプト取得
    try:
        transcript_data = client.get_transcript(meeting_id)
        transcript = format_transcript(transcript_data)
    except Exception as e:
        print(f"    Warning: Could not fetch transcript: {e}")
        transcript = "(トランスクリプト取得失敗)"

    # ハイライト取得
    try:
        highlights_data = client.get_highlights(meeting_id)
        highlights = format_highlights(highlights_data)
    except Exception as e:
        print(f"    Warning: Could not fetch highlights: {e}")
        highlights = "(ハイライト取得失敗)"

    # Markdownノート生成
    note_content = build_meeting_note(meeting, transcript, highlights)

    if dry_run:
        print(f"    [DRY RUN] Would save: {title}")
        print(f"    Content preview (first 500 chars):")
        print(f"    {note_content[:500]}...")
        return None

    # ファイル保存
    MEETING_DIR.mkdir(parents=True, exist_ok=True)
    meeting_date = meeting.get("date", meeting.get("createdAt", ""))
    try:
        dt = datetime.fromisoformat(meeting_date.replace("Z", "+00:00"))
        date_prefix = dt.strftime("%Y%m%d")
    except (ValueError, TypeError):
        date_prefix = datetime.now().strftime("%Y%m%d")

    safe_title = sanitize_filename(title)
    filepath = MEETING_DIR / f"{date_prefix}_{safe_title}.md"

    counter = 1
    while filepath.exists():
        filepath = MEETING_DIR / f"{date_prefix}_{safe_title}_{counter}.md"
        counter += 1

    filepath.write_text(note_content, encoding="utf-8")
    print(f"    Saved: {filepath.name}")
    return filepath


def main():
    parser = argparse.ArgumentParser(description="Sync tl;dv meetings to Obsidian Vault")
    parser.add_argument("--days", type=int, default=1,
                        help="Sync meetings from the last N days (default: 1)")
    parser.add_argument("--meeting-id", help="Sync a specific meeting by ID")
    parser.add_argument("--limit", type=int, default=20,
                        help="Max meetings to fetch (default: 20)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be synced without saving")
    parser.add_argument("--force", action="store_true",
                        help="Re-sync already synced meetings")
    parser.add_argument("--all", action="store_true",
                        help="Sync ALL meetings (full history)")
    parser.add_argument("--test", action="store_true",
                        help="Test API connection and show account info")

    args = parser.parse_args()

    api_key = os.environ.get("TLDV_API_KEY")
    if not api_key:
        print("Error: TLDV_API_KEY environment variable is required.")
        print("Get your API key from: https://tldv.io/app/settings/personal-settings/api-keys")
        sys.exit(1)

    client = TldvClient(api_key)
    state = load_sync_state()

    # --- 接続テストモード ---
    if args.test:
        print("=== tl;dv API Connection Test ===\n")
        result = client.test_connection()
        if result["api_key_valid"]:
            print("  API Key:    VALID")
            print(f"  Meetings:   accessible")
            details = result["details"]
            if details.get("total_meetings"):
                print(f"  Total:      {details['total_meetings']} meeting(s) found")
            first = details.get("first_meeting")
            if first:
                title = first.get("title", first.get("name", "N/A"))
                date = first.get("date", first.get("createdAt", "N/A"))
                print(f"\n  Latest meeting:")
                print(f"    Title: {title}")
                print(f"    Date:  {date}")
                print(f"    ID:    {first.get('id', first.get('meetingId', 'N/A'))}")
            print(f"\n  Sync state: {len(state['synced_ids'])} already synced")
            print(f"  Last sync:  {state.get('last_sync', 'never')}")
            print("\n  Connection test PASSED. Ready to sync.")
        else:
            print("  API Key:    INVALID or connection failed")
            print(f"  Error:      {result['details'].get('error', 'unknown')}")
            print("\n  Troubleshooting:")
            print("  1. Check TLDV_API_KEY is correct")
            print("  2. Ensure you have a Business or Enterprise plan")
            print("  3. Generate a new key at: https://tldv.io/app/settings/personal-settings/api-keys")
        return

    if args.meeting_id:
        # 特定のミーティングを同期
        print(f"Fetching meeting: {args.meeting_id}")
        meeting = client.get_meeting(args.meeting_id)
        sync_meeting(client, meeting, args.dry_run)
    elif args.all:
        # 全ミーティングを同期
        print("Fetching ALL meetings...")
        meetings = client.list_all_meetings()
        print(f"Found {len(meetings)} total meeting(s).")
        synced_count = 0

        for meeting in meetings:
            meeting_id = meeting.get("id", meeting.get("meetingId", ""))
            if not args.force and meeting_id in state["synced_ids"]:
                continue
            result = sync_meeting(client, meeting, args.dry_run)
            if result:
                state["synced_ids"].append(meeting_id)
                synced_count += 1

        if not args.dry_run:
            state["last_sync"] = datetime.now().isoformat()
            save_sync_state(state)
            print(f"\nSynced {synced_count} meeting(s) (total in vault: {len(state['synced_ids'])}).")
    else:
        # ミーティング一覧を取得して同期
        print(f"Fetching meetings from the last {args.days} day(s)...")
        meetings_data = client.list_meetings(limit=args.limit)

        meetings = meetings_data if isinstance(meetings_data, list) else meetings_data.get("meetings", meetings_data.get("results", []))

        cutoff = datetime.now() - timedelta(days=args.days)
        synced_count = 0

        for meeting in meetings:
            meeting_id = meeting.get("id", meeting.get("meetingId", ""))
            meeting_date = meeting.get("date", meeting.get("createdAt", ""))

            # 日付フィルター
            try:
                dt = datetime.fromisoformat(meeting_date.replace("Z", "+00:00"))
                if dt.replace(tzinfo=None) < cutoff:
                    continue
            except (ValueError, TypeError):
                pass

            # 同期済みチェック
            if not args.force and meeting_id in state["synced_ids"]:
                print(f"  Skipping (already synced): {meeting.get('title', meeting_id)}")
                continue

            result = sync_meeting(client, meeting, args.dry_run)
            if result:
                state["synced_ids"].append(meeting_id)
                synced_count += 1

        if not args.dry_run:
            state["last_sync"] = datetime.now().isoformat()
            save_sync_state(state)
            print(f"\nSynced {synced_count} meeting(s).")
        else:
            print(f"\n[DRY RUN] Would sync {synced_count} meeting(s).")


if __name__ == "__main__":
    main()
