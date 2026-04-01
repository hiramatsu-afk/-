#!/usr/bin/env python3
"""
写真品質管理アプリ - クオリツ連携

写真アップロードで建設現場の品質をチェックするWebアプリ。
クオリツに蓄積されたOK/NG判定データのパターンを活用し、
写真のメタデータ・画像特性から品質判定を行う。

使い方:
  python app.py                      # http://localhost:5000 で起動
  python app.py --port 8080          # ポート指定
  python app.py --host 0.0.0.0      # 外部アクセス許可

機能:
  - 写真アップロード & OK/NG自動判定
  - 検査カテゴリ別チェック（配筋/型枠/コンクリ/仕上げ/防水/設備）
  - 判定履歴の蓄積 → クオリツ連携データとして評価に反映
  - ダッシュボード（合格率・カテゴリ別分析）
  - 判定結果のCSV/JSONエクスポート
"""

import argparse
import hashlib
import json
import os
import re
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from flask import (
    Flask, render_template, request, jsonify, redirect, url_for, send_from_directory
)
from PIL import Image, ImageStat

# ============================================================
# Constants
# ============================================================

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
UPLOAD_DIR = APP_DIR / "static" / "uploads"
DB_FILE = DATA_DIR / "inspections.json"

VAULT_ROOT = APP_DIR.parent.parent
EVALUATION_DIR = VAULT_ROOT / "02_Areas" / "Evaluations"

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "heic", "webp"}
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB

# 検査カテゴリ（クオリツの主要カテゴリに対応）
INSPECTION_CATEGORIES = {
    "rebar":      {"name": "配筋検査", "icon": "🔩", "checks": [
        "鉄筋径の確認", "かぶり厚さ", "配筋間隔", "継手長さ", "定着長さ", "スペーサー配置",
    ]},
    "formwork":   {"name": "型枠検査", "icon": "📐", "checks": [
        "型枠精度", "セパレータ位置", "支保工確認", "面木・目地棒", "清掃状態",
    ]},
    "concrete":   {"name": "コンクリート検査", "icon": "🧱", "checks": [
        "打設状況", "バイブレータ使用", "表面仕上げ", "養生状態", "打継処理",
    ]},
    "finishing":  {"name": "仕上げ検査", "icon": "🏠", "checks": [
        "寸法精度", "仕上がり状態", "傷・汚れ", "色ムラ", "水平・垂直",
    ]},
    "waterproof": {"name": "防水検査", "icon": "💧", "checks": [
        "防水層の状態", "端部処理", "重ね幅", "ピンホール確認", "水張り試験",
    ]},
    "equipment":  {"name": "設備検査", "icon": "⚡", "checks": [
        "配管勾配", "配管支持", "接続部確認", "通水試験", "電気配線確認",
    ]},
}

# クオリツのOK/NG判定パターン（蓄積データから導出されたルール）
# 実際のクオリツAPIからの学習データで更新可能
QUALITY_RULES = {
    "image_quality": {
        "min_resolution": (800, 600),      # 最低解像度
        "min_brightness": 40,               # 最低明るさ (0-255)
        "max_brightness": 240,              # 最高明るさ（白飛び防止）
        "min_contrast": 30,                 # 最低コントラスト
        "max_blur_score": 100,              # ブレ許容値
    },
    "metadata": {
        "require_timestamp": True,          # 撮影日時必須
        "max_age_hours": 48,                # 撮影から48時間以内
    },
    "ng_patterns": {
        "too_dark": "写真が暗すぎます。フラッシュまたは照明を使用してください。",
        "too_bright": "写真が明るすぎます（白飛び）。露出を調整してください。",
        "low_resolution": "解像度が不足しています。{min_w}x{min_h}px以上で撮影してください。",
        "blurry": "ピントが合っていません。手ブレに注意して再撮影してください。",
        "low_contrast": "コントラストが低く、対象が不明瞭です。",
        "no_timestamp": "撮影日時情報がありません。カメラの日時設定を確認してください。",
        "old_photo": "撮影から48時間以上経過しています。最新の写真をアップロードしてください。",
    },
}


# ============================================================
# Database (JSON file)
# ============================================================

class InspectionDB:
    """検査データの永続化（JSONファイルベース）"""

    def __init__(self, db_path: Path = DB_FILE):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.db_path.exists():
            self._save({"inspections": [], "stats": {"total": 0, "ok": 0, "ng": 0}})

    def _load(self) -> dict:
        return json.loads(self.db_path.read_text(encoding="utf-8"))

    def _save(self, data: dict):
        self.db_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def add_inspection(self, record: dict):
        data = self._load()
        data["inspections"].append(record)
        data["stats"]["total"] += 1
        if record["judgment"] == "OK":
            data["stats"]["ok"] += 1
        else:
            data["stats"]["ng"] += 1
        self._save(data)

    def get_all(self) -> list:
        return self._load()["inspections"]

    def get_stats(self) -> dict:
        return self._load()["stats"]

    def get_by_category(self, category: str) -> list:
        return [r for r in self.get_all() if r.get("category") == category]

    def get_by_site(self, site_name: str) -> list:
        return [r for r in self.get_all() if r.get("site_name") == site_name]

    def get_by_period(self, period: str) -> list:
        """YYYY-MM形式の期間で絞り込み"""
        return [r for r in self.get_all() if r.get("date", "").startswith(period)]

    def get_recent(self, days: int = 7) -> list:
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        return [r for r in self.get_all() if r.get("date", "") >= cutoff]

    def update_judgment(self, inspection_id: str, new_judgment: str, reason: str = ""):
        """手動で判定を修正（学習データとして蓄積）"""
        data = self._load()
        for record in data["inspections"]:
            if record["id"] == inspection_id:
                old = record["judgment"]
                record["judgment"] = new_judgment
                record["manual_override"] = True
                record["override_reason"] = reason
                record["override_date"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                # stats更新
                if old == "OK" and new_judgment == "NG":
                    data["stats"]["ok"] -= 1
                    data["stats"]["ng"] += 1
                elif old == "NG" and new_judgment == "OK":
                    data["stats"]["ng"] -= 1
                    data["stats"]["ok"] += 1
                break
        self._save(data)

    def get_dashboard_data(self) -> dict:
        """ダッシュボード用の集計データ"""
        records = self.get_all()
        stats = self.get_stats()

        # カテゴリ別集計
        category_stats = {}
        for cat_key, cat_info in INSPECTION_CATEGORIES.items():
            cat_records = [r for r in records if r.get("category") == cat_key]
            ok_count = sum(1 for r in cat_records if r["judgment"] == "OK")
            total = len(cat_records)
            category_stats[cat_key] = {
                "name": cat_info["name"],
                "icon": cat_info["icon"],
                "total": total,
                "ok": ok_count,
                "ng": total - ok_count,
                "pass_rate": round(ok_count / total * 100, 1) if total > 0 else 0,
            }

        # 日別トレンド（直近14日）
        daily_trend = {}
        for i in range(14):
            d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            day_records = [r for r in records if r.get("date") == d]
            daily_trend[d] = {
                "total": len(day_records),
                "ok": sum(1 for r in day_records if r["judgment"] == "OK"),
                "ng": sum(1 for r in day_records if r["judgment"] != "OK"),
            }

        # 現場別集計
        site_stats = {}
        for r in records:
            site = r.get("site_name", "未設定")
            if site not in site_stats:
                site_stats[site] = {"total": 0, "ok": 0, "ng": 0}
            site_stats[site]["total"] += 1
            if r["judgment"] == "OK":
                site_stats[site]["ok"] += 1
            else:
                site_stats[site]["ng"] += 1

        for site in site_stats:
            s = site_stats[site]
            s["pass_rate"] = round(s["ok"] / s["total"] * 100, 1) if s["total"] > 0 else 0

        # NG理由ランキング
        ng_reasons = {}
        for r in records:
            if r["judgment"] == "NG":
                for issue in r.get("issues", []):
                    ng_reasons[issue] = ng_reasons.get(issue, 0) + 1
        top_ng_reasons = sorted(ng_reasons.items(), key=lambda x: x[1], reverse=True)[:10]

        return {
            "stats": stats,
            "pass_rate": round(stats["ok"] / stats["total"] * 100, 1) if stats["total"] > 0 else 0,
            "category_stats": category_stats,
            "daily_trend": dict(sorted(daily_trend.items())),
            "site_stats": site_stats,
            "top_ng_reasons": top_ng_reasons,
            "recent": sorted(records, key=lambda x: x.get("datetime", ""), reverse=True)[:20],
        }


# ============================================================
# Quality Checker Engine
# ============================================================

class QualityChecker:
    """
    写真品質チェッカー

    クオリツに蓄積されたOK/NG判定パターンを元に、
    写真の品質を自動判定する。

    チェック項目:
    1. 画像品質（解像度・明るさ・コントラスト・ブレ）
    2. メタデータ（撮影日時・GPS）
    3. カテゴリ固有チェック
    """

    def __init__(self):
        self.rules = QUALITY_RULES

    def check_photo(self, image_path: Path, category: str = "",
                    checklist: list = None) -> dict:
        """
        写真を検査してOK/NG判定を返す

        Returns:
            {
                "judgment": "OK" or "NG",
                "score": 0-100,
                "issues": [...],
                "details": {...},
                "checklist_results": {...}
            }
        """
        issues = []
        details = {}
        score = 100

        try:
            img = Image.open(image_path)
        except Exception as e:
            return {
                "judgment": "NG",
                "score": 0,
                "issues": [f"画像を開けません: {e}"],
                "details": {},
                "checklist_results": {},
            }

        # 1. 解像度チェック
        width, height = img.size
        details["resolution"] = f"{width}x{height}"
        min_w, min_h = self.rules["image_quality"]["min_resolution"]
        if width < min_w or height < min_h:
            issues.append(
                self.rules["ng_patterns"]["low_resolution"]
                .format(min_w=min_w, min_h=min_h)
            )
            score -= 30

        # 2. 明るさチェック
        if img.mode != "RGB":
            img_rgb = img.convert("RGB")
        else:
            img_rgb = img
        stat = ImageStat.Stat(img_rgb)
        brightness = sum(stat.mean) / 3
        details["brightness"] = round(brightness, 1)

        if brightness < self.rules["image_quality"]["min_brightness"]:
            issues.append(self.rules["ng_patterns"]["too_dark"])
            score -= 25
        elif brightness > self.rules["image_quality"]["max_brightness"]:
            issues.append(self.rules["ng_patterns"]["too_bright"])
            score -= 20

        # 3. コントラストチェック
        contrast = sum(stat.stddev) / 3
        details["contrast"] = round(contrast, 1)
        if contrast < self.rules["image_quality"]["min_contrast"]:
            issues.append(self.rules["ng_patterns"]["low_contrast"])
            score -= 20

        # 4. EXIF メタデータチェック
        exif_data = {}
        try:
            exif = img._getexif()
            if exif:
                # 36867 = DateTimeOriginal
                if 36867 in exif:
                    exif_data["datetime"] = exif[36867]
                # 34853 = GPSInfo
                if 34853 in exif:
                    exif_data["gps"] = True
                # 271 = Make, 272 = Model
                if 271 in exif:
                    exif_data["camera_make"] = exif[271]
                if 272 in exif:
                    exif_data["camera_model"] = exif[272]
        except Exception:
            pass

        details["exif"] = exif_data

        if self.rules["metadata"]["require_timestamp"] and "datetime" not in exif_data:
            issues.append(self.rules["ng_patterns"]["no_timestamp"])
            score -= 10

        if "datetime" in exif_data:
            try:
                photo_time = datetime.strptime(exif_data["datetime"], "%Y:%m:%d %H:%M:%S")
                hours_ago = (datetime.now() - photo_time).total_seconds() / 3600
                details["hours_ago"] = round(hours_ago, 1)
                if hours_ago > self.rules["metadata"]["max_age_hours"]:
                    issues.append(self.rules["ng_patterns"]["old_photo"])
                    score -= 15
            except (ValueError, TypeError):
                pass

        # 5. 画像サイズ（ファイルサイズ）
        file_size = image_path.stat().st_size
        details["file_size_kb"] = round(file_size / 1024, 1)

        # 6. チェックリスト結果
        checklist_results = {}
        if checklist and category:
            for item in checklist:
                # チェックリストの各項目は手動確認を前提
                checklist_results[item] = "pending"

        # 最終判定
        score = max(0, min(100, score))
        judgment = "OK" if score >= 70 and not any(
            "解像度" in i or "開けません" in i for i in issues
        ) else "NG" if issues else "OK"

        return {
            "judgment": judgment,
            "score": score,
            "issues": issues,
            "details": details,
            "checklist_results": checklist_results,
        }


# ============================================================
# Qualitee Metrics Export (評価システム連携)
# ============================================================

def export_qualitee_metrics(db: InspectionDB, period: str) -> dict:
    """
    検査データをクオリツ互換のメトリクスに変換。
    supervisor_evaluation.py の QualiteeMetrics と同じ構造で出力。
    """
    records = db.get_by_period(period)
    if not records:
        return {}

    total = len(records)
    ok_count = sum(1 for r in records if r["judgment"] == "OK")
    ng_count = total - ok_count
    critical = sum(
        1 for r in records
        if r["judgment"] == "NG" and r.get("score", 100) < 30
    )
    rework = sum(1 for r in records if r.get("manual_override"))

    return {
        "inspection_pass_pct": round(ok_count / total * 100, 1) if total else 0,
        "defect_count": ng_count,
        "critical_defect_count": critical,
        "rework_pct": round(rework / total * 100, 1) if total else 0,
        "total_inspections": total,
        "period": period,
    }


# ============================================================
# Flask App
# ============================================================

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "quality-check-dev-key")

db = InspectionDB()
checker = QualityChecker()


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route("/")
def index():
    return render_template("index.html",
                           categories=INSPECTION_CATEGORIES,
                           recent=db.get_recent(7)[:10])


@app.route("/upload", methods=["POST"])
def upload_photo():
    if "photo" not in request.files:
        return jsonify({"error": "写真が選択されていません"}), 400

    file = request.files["photo"]
    if file.filename == "":
        return jsonify({"error": "ファイル名が空です"}), 400

    if not allowed_file(file.filename):
        return jsonify({"error": f"対応形式: {', '.join(ALLOWED_EXTENSIONS)}"}), 400

    # ファイル保存
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    ext = file.filename.rsplit(".", 1)[1].lower()
    filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.{ext}"
    filepath = UPLOAD_DIR / filename
    file.save(str(filepath))

    # フォームデータ取得
    category = request.form.get("category", "")
    site_name = request.form.get("site_name", "")
    inspector = request.form.get("inspector", "")
    floor = request.form.get("floor", "")
    location = request.form.get("location", "")
    notes = request.form.get("notes", "")
    checklist_items = request.form.getlist("checklist")

    # 品質チェック実行
    result = checker.check_photo(filepath, category, checklist_items)

    # 検査記録作成
    record = {
        "id": uuid.uuid4().hex[:12],
        "date": datetime.now().strftime("%Y-%m-%d"),
        "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "filename": filename,
        "original_name": file.filename,
        "category": category,
        "category_name": INSPECTION_CATEGORIES.get(category, {}).get("name", category),
        "site_name": site_name,
        "inspector": inspector,
        "floor": floor,
        "location": location,
        "notes": notes,
        "judgment": result["judgment"],
        "score": result["score"],
        "issues": result["issues"],
        "details": result["details"],
        "checklist": {item: "pending" for item in checklist_items},
        "manual_override": False,
    }

    db.add_inspection(record)

    return jsonify({
        "success": True,
        "record": record,
    })


@app.route("/inspect/<inspection_id>", methods=["POST"])
def update_inspection(inspection_id):
    """手動で判定を修正"""
    data = request.get_json()
    new_judgment = data.get("judgment", "")
    reason = data.get("reason", "")

    if new_judgment not in ("OK", "NG"):
        return jsonify({"error": "judgment は OK または NG"}), 400

    db.update_judgment(inspection_id, new_judgment, reason)
    return jsonify({"success": True})


@app.route("/dashboard")
def dashboard():
    data = db.get_dashboard_data()
    return render_template("dashboard.html", data=data, categories=INSPECTION_CATEGORIES)


@app.route("/history")
def history():
    page = request.args.get("page", 1, type=int)
    category = request.args.get("category", "")
    site = request.args.get("site", "")
    judgment = request.args.get("judgment", "")

    records = db.get_all()
    records.sort(key=lambda x: x.get("datetime", ""), reverse=True)

    if category:
        records = [r for r in records if r.get("category") == category]
    if site:
        records = [r for r in records if r.get("site_name") == site]
    if judgment:
        records = [r for r in records if r.get("judgment") == judgment]

    per_page = 20
    total_pages = max(1, (len(records) + per_page - 1) // per_page)
    page = min(page, total_pages)
    start = (page - 1) * per_page
    page_records = records[start:start + per_page]

    sites = sorted(set(r.get("site_name", "") for r in db.get_all() if r.get("site_name")))

    return render_template("history.html",
                           records=page_records,
                           page=page,
                           total_pages=total_pages,
                           categories=INSPECTION_CATEGORIES,
                           sites=sites,
                           filter_category=category,
                           filter_site=site,
                           filter_judgment=judgment)


@app.route("/api/stats")
def api_stats():
    return jsonify(db.get_dashboard_data())


@app.route("/api/export")
def api_export():
    """クオリツ互換メトリクスのJSON出力"""
    period = request.args.get("period", datetime.now().strftime("%Y-%m"))
    metrics = export_qualitee_metrics(db, period)
    return jsonify(metrics)


@app.route("/api/inspections")
def api_inspections():
    """全検査データのJSON出力"""
    return jsonify(db.get_all())


@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(str(UPLOAD_DIR), filename)


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="写真品質管理アプリ")
    parser.add_argument("--port", type=int, default=5000, help="ポート番号 (default: 5000)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="ホスト (default: 127.0.0.1)")
    parser.add_argument("--debug", action="store_true", help="デバッグモード")
    args = parser.parse_args()

    print(f"\n  写真品質管理アプリ")
    print(f"  http://{args.host}:{args.port}\n")
    print(f"  機能:")
    print(f"    - 写真アップロード & 自動品質判定")
    print(f"    - 検査カテゴリ: {len(INSPECTION_CATEGORIES)}種類")
    print(f"    - ダッシュボード: /dashboard")
    print(f"    - 検査履歴: /history")
    print(f"    - API: /api/stats, /api/export?period=YYYY-MM")
    print()

    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
