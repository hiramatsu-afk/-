#!/usr/bin/env python3
"""
現場監督評価ダッシュボード生成スクリプト

保存済みの評価レポート（supervisor-evaluation）を集計し、
HTMLダッシュボードを生成する。

使い方:
  python generate_evaluation_dashboard.py
  python generate_evaluation_dashboard.py --open    # ブラウザで開く
  python generate_evaluation_dashboard.py --port 8080  # ローカルサーバー起動

生成先: vault/evaluation_dashboard.html
"""

import argparse
import html
import os
import re
import sys
import webbrowser
from collections import Counter
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

VAULT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_FILE = VAULT_ROOT / "evaluation_dashboard.html"
EXCLUDE_DIRS = {".obsidian", "scripts", "Templates", ".git"}


def iter_notes(folder=None):
    search_root = VAULT_ROOT / folder if folder else VAULT_ROOT
    notes = []
    for md in search_root.rglob("*.md"):
        if any(part in EXCLUDE_DIRS for part in md.relative_to(VAULT_ROOT).parts):
            continue
        notes.append(md)
    return sorted(notes, key=lambda p: p.stat().st_mtime, reverse=True)


def parse_frontmatter(content):
    fm = {}
    match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    if match:
        for line in match.group(1).split("\n"):
            if ":" in line:
                key, _, value = line.partition(":")
                fm[key.strip()] = value.strip().strip('"').strip("'")
    return fm


def extract_kpi_table(content, section_pattern):
    """Markdownテーブルからカテゴリ別KPIデータを抽出"""
    lines = content.split("\n")
    in_section = False
    rows = []
    for line in lines:
        if re.match(section_pattern, line, re.IGNORECASE):
            in_section = True
            continue
        if in_section and re.match(r'^#+\s', line):
            break
        if in_section and line.strip().startswith("|") and "---" not in line and "KPI" not in line:
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 4:
                rows.append({
                    "name": cells[0],
                    "target": cells[1],
                    "actual": cells[2],
                    "achievement": cells[3],
                    "score": cells[4] if len(cells) > 4 else "",
                })
    return rows


def collect_evaluation_data():
    all_notes = iter_notes()
    evaluations = []
    grade_counter = Counter()
    supervisor_data = {}

    for note in all_notes:
        content = note.read_text(encoding="utf-8", errors="replace")
        fm = parse_frontmatter(content)
        if fm.get("type") != "supervisor-evaluation":
            continue

        supervisor = fm.get("supervisor", "不明")
        period = fm.get("evaluation_period", "")
        grade = fm.get("grade", "?")
        score = float(fm.get("total_score", 0))
        site = fm.get("site_name", "")
        date = fm.get("date", "")

        grade_counter[grade] += 1

        # カテゴリ別スコアをMarkdownから抽出
        category_scores = {}
        for pattern, cat in [
            (r'^##\s*工程管理', "工程管理"),
            (r'^##\s*品質管理', "品質管理"),
            (r'^##\s*安全管理', "安全管理"),
            (r'^##\s*報告', "報告・コミュニケーション"),
        ]:
            match = re.search(pattern + r'.*?(\d+\.?\d*)点', content, re.MULTILINE)
            if match:
                category_scores[cat] = float(match.group(1))

        kpis = {
            "工程管理": extract_kpi_table(content, r'^##\s*工程管理'),
            "品質管理": extract_kpi_table(content, r'^##\s*品質管理'),
            "安全管理": extract_kpi_table(content, r'^##\s*安全管理'),
            "報告": extract_kpi_table(content, r'^##\s*報告'),
        }

        eval_data = {
            "supervisor": supervisor,
            "period": period,
            "grade": grade,
            "score": score,
            "site": site,
            "date": date,
            "category_scores": category_scores,
            "kpis": kpis,
            "path": str(note.relative_to(VAULT_ROOT)),
        }
        evaluations.append(eval_data)

        # 監督別トレンド
        if supervisor not in supervisor_data:
            supervisor_data[supervisor] = []
        supervisor_data[supervisor].append(eval_data)

    evaluations.sort(key=lambda x: (x["period"], x["supervisor"]), reverse=True)
    for v in supervisor_data.values():
        v.sort(key=lambda x: x["period"])

    return {
        "evaluations": evaluations,
        "grade_counter": dict(grade_counter),
        "supervisor_data": supervisor_data,
        "total_evaluations": len(evaluations),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def generate_html(data):
    evals = data["evaluations"]
    supervisors = data["supervisor_data"]
    grades = data["grade_counter"]

    avg_score = (
        round(sum(e["score"] for e in evals) / len(evals), 1)
        if evals else 0
    )
    top_grade_count = grades.get("S", 0) + grades.get("A", 0)

    # Grade color mapping
    grade_colors = {"S": "#9ece6a", "A": "#7aa2f7", "B": "#ff9e64", "C": "#f7768e", "D": "#db4b4b"}

    # Grade distribution badges
    grade_badges = ""
    for g in ["S", "A", "B", "C", "D"]:
        c = grades.get(g, 0)
        color = grade_colors.get(g, "#9aa5ce")
        if c > 0:
            grade_badges += f'<span class="grade-badge" style="background:{color};color:#1a1b26">{g}: {c}名</span> '

    # Supervisor ranking cards
    ranking_cards = ""
    latest_by_supervisor = {}
    for e in evals:
        s = e["supervisor"]
        if s not in latest_by_supervisor or e["period"] > latest_by_supervisor[s]["period"]:
            latest_by_supervisor[s] = e

    ranked = sorted(latest_by_supervisor.values(), key=lambda x: x["score"], reverse=True)
    for i, e in enumerate(ranked, 1):
        grade_color = grade_colors.get(e["grade"], "#9aa5ce")
        bar_width = int(e["score"])

        # Category bars
        cat_bars = ""
        for cat in ["工程管理", "品質管理", "安全管理", "報告・コミュニケーション"]:
            cat_score = e["category_scores"].get(cat, 0)
            cat_width = int(cat_score)
            cat_bars += f'''
            <div class="cat-row">
              <span class="cat-label">{html.escape(cat)}</span>
              <div class="cat-bar-bg"><div class="cat-bar" style="width:{cat_width}%"></div></div>
              <span class="cat-score">{cat_score}</span>
            </div>'''

        # Trend sparkline (text-based)
        history = supervisors.get(e["supervisor"], [])
        trend = " → ".join(f'{h["grade"]}({h["score"]})' for h in history[-5:])

        ranking_cards += f'''
        <div class="card eval-card" data-search="{html.escape((e['supervisor'] + ' ' + e['site'] + ' ' + e['grade']).lower())}">
          <div class="card-header">
            <span class="rank">#{i}</span>
            <span class="grade-large" style="color:{grade_color}">{html.escape(e['grade'])}</span>
          </div>
          <h3>{html.escape(e['supervisor'])}</h3>
          <div class="site-name">{html.escape(e['site'])}</div>
          <div class="score-bar-container">
            <div class="score-bar" style="width:{bar_width}%;background:{grade_color}"></div>
            <span class="score-label">{e['score']}/100</span>
          </div>
          <div class="category-breakdown">{cat_bars}</div>
          <div class="trend">推移: {html.escape(trend)}</div>
          <div class="period">評価期間: {html.escape(e['period'])}</div>
        </div>'''

    # All evaluations table
    eval_rows = ""
    for e in evals:
        grade_color = grade_colors.get(e["grade"], "#9aa5ce")
        eval_rows += f'''
        <tr data-search="{html.escape((e['supervisor'] + ' ' + e['site'] + ' ' + e['period']).lower())}">
          <td>{html.escape(e['period'])}</td>
          <td><strong>{html.escape(e['supervisor'])}</strong></td>
          <td>{html.escape(e['site'])}</td>
          <td><span class="grade-badge-sm" style="background:{grade_color};color:#1a1b26">{html.escape(e['grade'])}</span></td>
          <td>{e['score']}</td>
          <td>{e['category_scores'].get('工程管理', '-')}</td>
          <td>{e['category_scores'].get('品質管理', '-')}</td>
          <td>{e['category_scores'].get('安全管理', '-')}</td>
          <td>{e['category_scores'].get('報告・コミュニケーション', '-')}</td>
        </tr>'''

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>現場監督評価ダッシュボード</title>
<style>
  :root {{
    --bg: #1a1b26; --surface: #24283b; --surface2: #2f3347;
    --text: #c0caf5; --text2: #9aa5ce; --accent: #7aa2f7;
    --green: #9ece6a; --orange: #ff9e64; --red: #f7768e;
    --purple: #bb9af7; --cyan: #7dcfff;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, 'Segoe UI', 'Hiragino Kaku Gothic ProN', sans-serif; background: var(--bg); color: var(--text); line-height: 1.6; }}

  .header {{ background: var(--surface); padding: 20px 30px; border-bottom: 1px solid var(--surface2); display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 15px; }}
  .header h1 {{ font-size: 1.4em; color: var(--accent); }}
  .header .subtitle {{ font-size: 0.85em; color: var(--text2); }}
  .header .meta {{ color: var(--text2); font-size: 0.85em; }}

  .search-bar {{ padding: 15px 30px; background: var(--surface); border-bottom: 1px solid var(--surface2); position: sticky; top: 0; z-index: 100; }}
  .search-bar input {{ width: 100%; padding: 12px 18px; border-radius: 8px; border: 1px solid var(--surface2); background: var(--bg); color: var(--text); font-size: 1em; outline: none; }}
  .search-bar input:focus {{ border-color: var(--accent); }}
  .search-bar input::placeholder {{ color: var(--text2); }}

  .container {{ max-width: 1400px; margin: 0 auto; padding: 20px; }}

  .stats-row {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 15px; margin-bottom: 25px; }}
  .stat-card {{ background: var(--surface); padding: 18px; border-radius: 10px; text-align: center; }}
  .stat-card .number {{ font-size: 2em; font-weight: bold; color: var(--accent); }}
  .stat-card .label {{ font-size: 0.85em; color: var(--text2); margin-top: 4px; }}

  .tabs {{ display: flex; gap: 8px; margin-bottom: 20px; flex-wrap: wrap; }}
  .tab {{ padding: 8px 18px; border-radius: 20px; background: var(--surface); color: var(--text2); cursor: pointer; border: 1px solid transparent; font-size: 0.9em; transition: all 0.2s; }}
  .tab:hover {{ border-color: var(--accent); }}
  .tab.active {{ background: var(--accent); color: var(--bg); font-weight: 600; }}

  .tab-content {{ display: none; }}
  .tab-content.active {{ display: block; }}

  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(380px, 1fr)); gap: 18px; }}

  .card {{ background: var(--surface); border-radius: 12px; padding: 20px; border: 1px solid var(--surface2); transition: border-color 0.2s; }}
  .card:hover {{ border-color: var(--accent); }}
  .card-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }}
  .card h3 {{ font-size: 1.15em; margin-bottom: 4px; color: var(--text); }}

  .rank {{ font-size: 1.4em; font-weight: bold; color: var(--text2); }}
  .grade-large {{ font-size: 2em; font-weight: bold; }}
  .site-name {{ font-size: 0.85em; color: var(--text2); margin-bottom: 12px; }}

  .score-bar-container {{ position: relative; height: 28px; background: var(--surface2); border-radius: 14px; margin-bottom: 14px; overflow: hidden; }}
  .score-bar {{ height: 100%; border-radius: 14px; transition: width 0.6s ease; }}
  .score-label {{ position: absolute; right: 12px; top: 50%; transform: translateY(-50%); font-weight: bold; font-size: 0.9em; }}

  .category-breakdown {{ margin: 10px 0; }}
  .cat-row {{ display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }}
  .cat-label {{ font-size: 0.78em; color: var(--text2); width: 130px; text-align: right; flex-shrink: 0; }}
  .cat-bar-bg {{ flex: 1; height: 8px; background: var(--surface2); border-radius: 4px; overflow: hidden; }}
  .cat-bar {{ height: 100%; background: var(--accent); border-radius: 4px; transition: width 0.6s ease; }}
  .cat-score {{ font-size: 0.78em; color: var(--text2); width: 35px; }}

  .trend {{ font-size: 0.8em; color: var(--text2); margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--surface2); }}
  .period {{ font-size: 0.78em; color: var(--text2); margin-top: 4px; }}

  .grade-badge {{ display: inline-block; padding: 4px 14px; border-radius: 12px; font-size: 0.9em; font-weight: 700; margin: 2px; }}
  .grade-badge-sm {{ display: inline-block; padding: 2px 10px; border-radius: 10px; font-size: 0.8em; font-weight: 700; }}

  table {{ width: 100%; border-collapse: collapse; }}
  th {{ background: var(--surface2); color: var(--text2); padding: 10px 12px; text-align: left; font-size: 0.85em; position: sticky; top: 0; }}
  td {{ padding: 10px 12px; border-bottom: 1px solid var(--surface2); font-size: 0.9em; }}
  tr:hover td {{ background: var(--surface2); }}

  .legend {{ display: flex; gap: 15px; flex-wrap: wrap; margin-bottom: 15px; }}
  .legend-item {{ display: flex; align-items: center; gap: 6px; font-size: 0.85em; color: var(--text2); }}
  .legend-dot {{ width: 12px; height: 12px; border-radius: 50%; }}

  .hidden {{ display: none !important; }}

  @media (max-width: 900px) {{
    .grid {{ grid-template-columns: 1fr; }}
    .stats-row {{ grid-template-columns: repeat(2, 1fr); }}
  }}
</style>
</head>
<body>

<div class="header">
  <div>
    <h1>現場監督評価ダッシュボード</h1>
    <div class="subtitle">識学 × ANDPAD × クオリツ</div>
  </div>
  <div class="meta">
    更新: {data['generated_at']} | {data['total_evaluations']}件の評価
  </div>
</div>

<div class="search-bar">
  <input type="text" id="searchInput" placeholder="監督名、現場名で検索...">
</div>

<div class="container">
  <div class="stats-row">
    <div class="stat-card">
      <div class="number">{data['total_evaluations']}</div>
      <div class="label">総評価数</div>
    </div>
    <div class="stat-card">
      <div class="number">{len(supervisors)}</div>
      <div class="label">評価対象者</div>
    </div>
    <div class="stat-card">
      <div class="number">{avg_score}</div>
      <div class="label">平均スコア</div>
    </div>
    <div class="stat-card">
      <div class="number">{top_grade_count}</div>
      <div class="label">S・Aグレード</div>
    </div>
    <div class="stat-card">
      <div class="number" style="font-size:0.9em">{grade_badges}</div>
      <div class="label">グレード分布</div>
    </div>
  </div>

  <div class="legend">
    <div class="legend-item"><div class="legend-dot" style="background:#9ece6a"></div> S (95+)</div>
    <div class="legend-item"><div class="legend-dot" style="background:#7aa2f7"></div> A (85+)</div>
    <div class="legend-item"><div class="legend-dot" style="background:#ff9e64"></div> B (70+)</div>
    <div class="legend-item"><div class="legend-dot" style="background:#f7768e"></div> C (55+)</div>
    <div class="legend-item"><div class="legend-dot" style="background:#db4b4b"></div> D (&lt;55)</div>
  </div>

  <div class="tabs">
    <div class="tab active" data-tab="ranking">ランキング</div>
    <div class="tab" data-tab="all">全評価一覧</div>
  </div>

  <div class="tab-content active" id="tab-ranking">
    <div class="grid">{ranking_cards}</div>
  </div>

  <div class="tab-content" id="tab-all">
    <div style="overflow-x:auto;">
      <table>
        <thead>
          <tr>
            <th>期間</th>
            <th>監督名</th>
            <th>現場</th>
            <th>グレード</th>
            <th>スコア</th>
            <th>工程管理</th>
            <th>品質管理</th>
            <th>安全管理</th>
            <th>報告</th>
          </tr>
        </thead>
        <tbody>{eval_rows}</tbody>
      </table>
    </div>
  </div>
</div>

<script>
document.querySelectorAll('.tab').forEach(tab => {{
  tab.addEventListener('click', () => {{
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(tc => tc.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById('tab-' + tab.dataset.tab).classList.add('active');
  }});
}});

const searchInput = document.getElementById('searchInput');
searchInput.addEventListener('input', () => {{
  const q = searchInput.value.toLowerCase().trim();
  document.querySelectorAll('.card, tr[data-search]').forEach(el => {{
    const text = el.dataset.search || el.textContent.toLowerCase();
    el.classList.toggle('hidden', q && !text.includes(q));
  }});
}});
</script>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="現場監督評価ダッシュボード生成")
    parser.add_argument("--open", "-o", action="store_true", help="生成後にブラウザで開く")
    parser.add_argument("--port", "-p", type=int, help="ローカルサーバーのポート番号")
    args = parser.parse_args()

    print("評価データを収集中...")
    data = collect_evaluation_data()

    if data["total_evaluations"] == 0:
        print("評価データがありません。先に supervisor_evaluation.py --evaluate を実行してください。")
        sys.exit(0)

    print("ダッシュボード生成中...")
    html_content = generate_html(data)
    OUTPUT_FILE.write_text(html_content, encoding="utf-8")
    print(f"ダッシュボード保存: {OUTPUT_FILE}")

    if args.port:
        os.chdir(str(VAULT_ROOT))
        print(f"\nServing at http://localhost:{args.port}/evaluation_dashboard.html")
        print("Press Ctrl+C to stop.\n")
        httpd = HTTPServer(("", args.port), SimpleHTTPRequestHandler)
        webbrowser.open(f"http://localhost:{args.port}/evaluation_dashboard.html")
        httpd.serve_forever()
    elif args.open:
        webbrowser.open(str(OUTPUT_FILE))


if __name__ == "__main__":
    main()
