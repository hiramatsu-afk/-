#!/usr/bin/env python3
"""
gdrive_sync.py - Google Drive → Obsidian Vault 同期ツール

Google Drive上のドキュメントをObsidian Vaultに取り込む。
スプレッドシート、ドキュメント、スライドをMarkdownに変換して保存。

セットアップ:
    1. Google Cloud Console で OAuth 2.0 クライアントIDを作成
       → https://console.cloud.google.com/apis/credentials
    2. Google Drive API と Google Sheets API を有効化
    3. credentials.json をダウンロードして vault/scripts/ に配置
    4. pip install google-auth google-auth-oauthlib google-api-python-client

使い方:
    python vault/scripts/gdrive_sync.py --setup              # 初回認証
    python vault/scripts/gdrive_sync.py --list                # Drive内ファイル一覧
    python vault/scripts/gdrive_sync.py --sync-folder FOLDER_ID  # フォルダ同期
    python vault/scripts/gdrive_sync.py --sync-file FILE_ID   # 個別ファイル同期
    python vault/scripts/gdrive_sync.py --sync-sheet SHEET_ID # スプレッドシート同期
    python vault/scripts/gdrive_sync.py --watch FOLDER_ID     # 変更監視（定期実行用）
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
VAULT_DIR = SCRIPT_DIR.parent
TOKEN_PATH = SCRIPT_DIR / 'gdrive_token.json'
CREDENTIALS_PATH = SCRIPT_DIR / 'credentials.json'
SYNC_STATE_PATH = SCRIPT_DIR / '.gdrive_sync_state.json'

# Google API のインポート（未インストール時はガイドを表示）
try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    GOOGLE_API_AVAILABLE = True
except ImportError:
    GOOGLE_API_AVAILABLE = False

SCOPES = [
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/spreadsheets.readonly',
]


def check_dependencies():
    """依存パッケージの確認"""
    if not GOOGLE_API_AVAILABLE:
        print("❌ Google API ライブラリが未インストールです。")
        print("\n以下のコマンドでインストールしてください:")
        print("  pip install google-auth google-auth-oauthlib google-api-python-client")
        print("\nまた、Google Cloud Console で以下の設定が必要です:")
        print("  1. プロジェクト作成")
        print("  2. Google Drive API / Google Sheets API を有効化")
        print("  3. OAuth 2.0 クライアントID を作成（デスクトップアプリ）")
        print(f"  4. credentials.json を {CREDENTIALS_PATH} に配置")
        sys.exit(1)


def get_credentials():
    """OAuth認証情報を取得・更新"""
    creds = None

    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_PATH.exists():
                print(f"❌ {CREDENTIALS_PATH} が見つかりません。")
                print("Google Cloud Console からダウンロードしてください。")
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_PATH), SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_PATH, 'w') as token:
            token.write(creds.to_json())
            print("✅ 認証トークンを保存しました。")

    return creds


def load_sync_state():
    """同期状態を読み込む"""
    if SYNC_STATE_PATH.exists():
        with open(SYNC_STATE_PATH, 'r') as f:
            return json.load(f)
    return {'synced_files': {}}


def save_sync_state(state):
    """同期状態を保存"""
    with open(SYNC_STATE_PATH, 'w') as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def export_gdoc_to_markdown(service, file_id, title):
    """Google ドキュメントをMarkdownとしてエクスポート"""
    # Google Docs は text/plain でエクスポートしてMarkdown変換
    content = service.files().export(
        fileId=file_id, mimeType='text/plain').execute()
    text = content.decode('utf-8') if isinstance(content, bytes) else content

    frontmatter = f"""---
type: resource
source: Google Drive
gdrive_id: "{file_id}"
date: {datetime.now().strftime('%Y-%m-%d')}
tags: [gdrive, document]
status: synced
---

"""
    return frontmatter + f"# {title}\n\n" + text


def export_sheet_to_markdown(sheets_service, spreadsheet_id, title):
    """Google スプレッドシートをMarkdownテーブルに変換"""
    spreadsheet = sheets_service.spreadsheets().get(
        spreadsheetId=spreadsheet_id).execute()

    all_content = f"""---
type: resource
source: Google Drive
subtype: spreadsheet
gdrive_id: "{spreadsheet_id}"
date: {datetime.now().strftime('%Y-%m-%d')}
tags: [gdrive, spreadsheet]
status: synced
---

# {title}

"""

    for sheet in spreadsheet.get('sheets', []):
        sheet_name = sheet['properties']['title']
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"'{sheet_name}'").execute()
        rows = result.get('values', [])

        all_content += f"## {sheet_name}\n\n"

        if rows:
            # ヘッダー行
            header = rows[0]
            all_content += "| " + " | ".join(str(c) for c in header) + " |\n"
            all_content += "| " + " | ".join("---" for _ in header) + " |\n"

            # データ行
            for row in rows[1:]:
                # 列数を合わせる
                padded = row + [''] * (len(header) - len(row))
                all_content += "| " + " | ".join(str(c) for c in padded[:len(header)]) + " |\n"

            all_content += "\n"

    return all_content


def sanitize_filename(name):
    """ファイル名をサニタイズ"""
    # 危険な文字を除去
    name = re.sub(r'[<>:"/\\|?*]', '', name) if 'import re' else name
    for ch in ['<', '>', ':', '"', '/', '\\', '|', '?', '*']:
        name = name.replace(ch, '')
    return name.strip()


def cmd_setup():
    """初回セットアップ"""
    check_dependencies()
    print("🔐 Google Drive 認証を開始します...")
    creds = get_credentials()
    service = build('drive', 'v3', credentials=creds)

    # 接続テスト
    about = service.about().get(fields='user').execute()
    user = about.get('user', {})
    print(f"✅ 認証成功: {user.get('displayName', '')} ({user.get('emailAddress', '')})")


def cmd_list(folder_id=None):
    """ファイル一覧を表示"""
    check_dependencies()
    creds = get_credentials()
    service = build('drive', 'v3', credentials=creds)

    query = f"'{folder_id}' in parents" if folder_id else None
    if query:
        query += " and trashed = false"
    else:
        query = "trashed = false"

    results = service.files().list(
        q=query,
        pageSize=50,
        fields="files(id, name, mimeType, modifiedTime)",
        orderBy="modifiedTime desc"
    ).execute()

    files = results.get('files', [])
    if not files:
        print("ファイルが見つかりません。")
        return

    print(f"📁 ファイル一覧 ({len(files)}件)")
    print("-" * 70)
    for f in files:
        mime = f.get('mimeType', '')
        icon = '📄'
        if 'folder' in mime:
            icon = '📁'
        elif 'spreadsheet' in mime:
            icon = '📊'
        elif 'presentation' in mime:
            icon = '📽️'
        elif 'document' in mime:
            icon = '📝'

        modified = f.get('modifiedTime', '')[:10]
        print(f"  {icon} [{modified}] {f['name']}")
        print(f"     ID: {f['id']}")


def cmd_sync_folder(folder_id, dest_folder='03_Resources'):
    """フォルダ内のファイルを一括同期"""
    check_dependencies()
    creds = get_credentials()
    drive_service = build('drive', 'v3', credentials=creds)
    sheets_service = build('sheets', 'v4', credentials=creds)

    state = load_sync_state()

    results = drive_service.files().list(
        q=f"'{folder_id}' in parents and trashed = false",
        fields="files(id, name, mimeType, modifiedTime)"
    ).execute()

    files = results.get('files', [])
    dest_path = VAULT_DIR / dest_folder
    dest_path.mkdir(parents=True, exist_ok=True)

    synced = 0
    skipped = 0

    for f in files:
        file_id = f['id']
        title = f['name']
        mime = f.get('mimeType', '')
        modified = f.get('modifiedTime', '')

        # 変更チェック
        if file_id in state['synced_files']:
            if state['synced_files'][file_id].get('modifiedTime') == modified:
                skipped += 1
                continue

        try:
            if 'document' in mime:
                content = export_gdoc_to_markdown(drive_service, file_id, title)
            elif 'spreadsheet' in mime:
                content = export_sheet_to_markdown(sheets_service, file_id, title)
            else:
                skipped += 1
                continue

            safe_name = sanitize_filename(title)
            filename = f"{datetime.now().strftime('%Y%m%d')}_{safe_name}.md"
            filepath = dest_path / filename

            with open(filepath, 'w', encoding='utf-8') as out:
                out.write(content)

            state['synced_files'][file_id] = {
                'name': title,
                'modifiedTime': modified,
                'local_path': str(filepath.relative_to(VAULT_DIR)),
                'synced_at': datetime.now().isoformat(),
            }
            synced += 1
            print(f"  ✅ {title} → {filepath.name}")

        except Exception as e:
            print(f"  ❌ {title}: {e}")

    save_sync_state(state)
    print(f"\n同期完了: {synced}件同期, {skipped}件スキップ")


def cmd_sync_file(file_id, dest_folder='03_Resources'):
    """個別ファイルを同期"""
    check_dependencies()
    creds = get_credentials()
    drive_service = build('drive', 'v3', credentials=creds)
    sheets_service = build('sheets', 'v4', credentials=creds)

    file_meta = drive_service.files().get(
        fileId=file_id, fields='id,name,mimeType,modifiedTime').execute()

    title = file_meta['name']
    mime = file_meta.get('mimeType', '')

    if 'spreadsheet' in mime:
        content = export_sheet_to_markdown(sheets_service, file_id, title)
    elif 'document' in mime:
        content = export_gdoc_to_markdown(drive_service, file_id, title)
    else:
        print(f"❌ 未対応のファイル形式: {mime}")
        return

    dest_path = VAULT_DIR / dest_folder
    dest_path.mkdir(parents=True, exist_ok=True)

    safe_name = sanitize_filename(title)
    filename = f"{datetime.now().strftime('%Y%m%d')}_{safe_name}.md"
    filepath = dest_path / filename

    with open(filepath, 'w', encoding='utf-8') as out:
        out.write(content)

    print(f"✅ {title} → {filepath}")


def main():
    parser = argparse.ArgumentParser(
        description='Google Drive → Obsidian Vault 同期')
    parser.add_argument('--setup', action='store_true',
                        help='初回認証セットアップ')
    parser.add_argument('--list', nargs='?', const='root', default=None,
                        help='ファイル一覧（オプション: フォルダID）')
    parser.add_argument('--sync-folder', type=str,
                        help='フォルダ同期（フォルダID）')
    parser.add_argument('--sync-file', type=str,
                        help='個別ファイル同期（ファイルID）')
    parser.add_argument('--dest', type=str, default='03_Resources',
                        help='保存先フォルダ（デフォルト: 03_Resources）')

    args = parser.parse_args()

    if args.setup:
        cmd_setup()
    elif args.list is not None:
        folder_id = None if args.list == 'root' else args.list
        cmd_list(folder_id)
    elif args.sync_folder:
        cmd_sync_folder(args.sync_folder, args.dest)
    elif args.sync_file:
        cmd_sync_file(args.sync_file, args.dest)
    else:
        parser.print_help()
        print("\n💡 まずは --setup で認証を行ってください。")


if __name__ == '__main__':
    main()
