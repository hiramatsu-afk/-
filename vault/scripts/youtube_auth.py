#!/usr/bin/env python3
"""YouTube OAuth認証ヘルパー（ヘッドレス環境用）

ブラウザがない環境でもOAuth認証を完了できるスクリプト。
リダイレクトURLからコードを抽出してトークンを保存する。
"""

import json
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
CONFIG_DIR = Path(__file__).parent / "youtube_config"
CLIENT_SECRET_PATH = CONFIG_DIR / "client_secret.json"
TOKEN_PATH = CONFIG_DIR / "token.json"


def main():
    if TOKEN_PATH.exists():
        print(f"トークンファイルが既に存在します: {TOKEN_PATH}")
        ans = input("上書きしますか？ (y/N): ").strip().lower()
        if ans != "y":
            print("中止しました。")
            return

    flow = InstalledAppFlow.from_client_secrets_file(
        str(CLIENT_SECRET_PATH), SCOPES,
        redirect_uri="http://localhost"
    )

    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
    )

    print("\n" + "=" * 60)
    print("以下のURLをブラウザで開いてください:")
    print("=" * 60)
    print(f"\n{auth_url}\n")
    print("=" * 60)
    print("Googleアカウントでログイン後、")
    print("「localhost に接続できません」のようなエラーページが表示されます。")
    print("そのページのURLバー全体をコピーして、以下に貼り付けてください。")
    print("=" * 60)

    redirect_url = input("\nリダイレクトURL: ").strip()

    # URLからauthorization codeを抽出
    parsed = urlparse(redirect_url)
    params = parse_qs(parsed.query)

    if "code" not in params:
        print("エラー: URLに認証コードが含まれていません。")
        print(f"取得したパラメータ: {list(params.keys())}")
        return

    code = params["code"][0]
    flow.fetch_token(code=code)
    creds = flow.credentials

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(TOKEN_PATH, "w") as f:
        f.write(creds.to_json())

    print(f"\n認証成功！トークンを保存しました: {TOKEN_PATH}")


if __name__ == "__main__":
    main()
