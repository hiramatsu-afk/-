#!/usr/bin/env python3
"""
現場監督評価システム - 識学 × ANDPAD × クオリツ

識学の評価原則（結果の定量化・位置の明確化・曖昧さの排除）に基づき、
ANDPADの工程管理データとクオリツの品質管理データから現場監督を評価する。

使い方:
  # 現場監督を評価（シミュレーションモード）
  python supervisor_evaluation.py --evaluate --name "田中太郎" --site "A現場マンション新築工事" --period 2026-03

  # 厳格モード（識学の完全二値評価: 達成/未達成のみ）
  python supervisor_evaluation.py --evaluate --name "田中太郎" --site "A現場" --period 2026-03 --strict

  # 複数監督の一括評価
  python supervisor_evaluation.py --evaluate-all --period 2026-03

  # 保存済み評価の一覧表示
  python supervisor_evaluation.py --list

  # 期間サマリー（全監督の比較）
  python supervisor_evaluation.py --summary --period 2026-03

  # ANDPADプロジェクトIDを指定して評価
  python supervisor_evaluation.py --evaluate --name "田中太郎" --site "A現場" --project-id PJ-001 --period 2026-03

環境変数:
  ANDPAD_API_KEY   - ANDPAD APIキー（未設定時はシミュレーションデータ）
  QUALITEE_API_KEY - クオリツ APIキー（未設定時はシミュレーションデータ）
"""

import argparse
import json
import os
import random
import re
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None

VAULT_ROOT = Path(__file__).resolve().parent.parent
EVALUATION_DIR = VAULT_ROOT / "02_Areas" / "Evaluations"

# ============================================================
# Data Models
# ============================================================

@dataclass
class AndpadMetrics:
    """ANDPADから取得する工程管理指標"""
    schedule_adherence_pct: float = 0.0       # 工程遵守率 (%)
    milestone_completion_pct: float = 0.0     # マイルストーン達成率 (%)
    delayed_tasks: int = 0                     # 遅延タスク数
    report_submission_pct: float = 0.0        # 報告書提出率 (%)
    photo_upload_count: int = 0                # 写真アップロード数
    avg_response_hours: float = 0.0           # 平均応答時間 (時間)


@dataclass
class QualiteeMetrics:
    """クオリツから取得する品質・安全管理指標"""
    inspection_pass_pct: float = 0.0          # 検査合格率 (%)
    defect_count: int = 0                      # 不具合数
    critical_defect_count: int = 0             # 重大不具合数
    rework_pct: float = 0.0                    # 手戻り率 (%)
    safety_violation_count: int = 0            # 安全違反件数
    checklist_completion_pct: float = 0.0     # チェックリスト完了率 (%)


@dataclass
class KPIResult:
    """個別KPIの評価結果"""
    name: str
    category: str
    target: float
    actual: float
    unit: str
    weight: float
    lower_is_better: bool = False
    score: float = 0.0       # 0-100
    achieved: bool = False   # 識学式: 達成/未達成


@dataclass
class EvaluationResult:
    """評価結果全体"""
    supervisor_name: str
    site_name: str
    project_id: str
    period: str
    evaluation_date: str
    kpi_results: list = field(default_factory=list)
    category_scores: dict = field(default_factory=dict)
    total_score: float = 0.0
    grade: str = ""
    strengths: list = field(default_factory=list)
    improvements: list = field(default_factory=list)
    feedback: list = field(default_factory=list)


# ============================================================
# KPI Definitions (識学: 位置の明確化 - 役割に紐づくKPI)
# ============================================================

KPI_DEFINITIONS = {
    "工程管理": [
        {"name": "工程遵守率", "target": 95.0, "unit": "%", "weight": 0.15,
         "lower_is_better": False, "source": "andpad", "field": "schedule_adherence_pct"},
        {"name": "マイルストーン達成率", "target": 100.0, "unit": "%", "weight": 0.10,
         "lower_is_better": False, "source": "andpad", "field": "milestone_completion_pct"},
        {"name": "遅延タスク数", "target": 0.0, "unit": "件", "weight": 0.05,
         "lower_is_better": True, "source": "andpad", "field": "delayed_tasks"},
    ],
    "品質管理": [
        {"name": "検査合格率", "target": 98.0, "unit": "%", "weight": 0.15,
         "lower_is_better": False, "source": "qualitee", "field": "inspection_pass_pct"},
        {"name": "手戻り率", "target": 2.0, "unit": "%", "weight": 0.10,
         "lower_is_better": True, "source": "qualitee", "field": "rework_pct"},
        {"name": "重大不具合数", "target": 0.0, "unit": "件", "weight": 0.10,
         "lower_is_better": True, "source": "qualitee", "field": "critical_defect_count"},
    ],
    "安全管理": [
        {"name": "安全違反件数", "target": 0.0, "unit": "件", "weight": 0.10,
         "lower_is_better": True, "source": "qualitee", "field": "safety_violation_count"},
        {"name": "チェックリスト完了率", "target": 100.0, "unit": "%", "weight": 0.05,
         "lower_is_better": False, "source": "qualitee", "field": "checklist_completion_pct"},
    ],
    "報告・コミュニケーション": [
        {"name": "報告書提出率", "target": 100.0, "unit": "%", "weight": 0.10,
         "lower_is_better": False, "source": "andpad", "field": "report_submission_pct"},
        {"name": "写真アップロード数", "target": 50.0, "unit": "枚", "weight": 0.05,
         "lower_is_better": False, "source": "andpad", "field": "photo_upload_count"},
        {"name": "平均応答時間", "target": 2.0, "unit": "時間", "weight": 0.05,
         "lower_is_better": True, "source": "andpad", "field": "avg_response_hours"},
    ],
}

# 識学グレード閾値（曖昧さの排除: 明確な基準）
GRADE_THRESHOLDS = [
    (95, "S", "卓越"),
    (85, "A", "優秀"),
    (70, "B", "標準"),
    (55, "C", "要改善"),
    (0,  "D", "要指導"),
]


# ============================================================
# API Clients
# ============================================================

class AndpadClient:
    """ANDPAD APIクライアント"""

    def __init__(self, api_key: str = ""):
        self.api_key = api_key
        self.base_url = "https://api.andpad.jp/v1"

    def get_metrics(self, project_id: str, period: str) -> AndpadMetrics:
        if not self.api_key:
            return self._simulate(project_id, period)
        if requests is None:
            print("Warning: requests not installed. Using simulation data.")
            return self._simulate(project_id, period)

        # Real API integration point
        session = requests.Session()
        session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        })
        try:
            resp = session.get(
                f"{self.base_url}/projects/{project_id}/metrics",
                params={"period": period},
            )
            resp.raise_for_status()
            data = resp.json()
            return AndpadMetrics(
                schedule_adherence_pct=data.get("schedule_adherence", 0),
                milestone_completion_pct=data.get("milestone_completion", 0),
                delayed_tasks=data.get("delayed_tasks", 0),
                report_submission_pct=data.get("report_submission", 0),
                photo_upload_count=data.get("photo_count", 0),
                avg_response_hours=data.get("avg_response_hours", 0),
            )
        except Exception as e:
            print(f"ANDPAD API error: {e}. Falling back to simulation.")
            return self._simulate(project_id, period)

    def _simulate(self, project_id: str, period: str) -> AndpadMetrics:
        """シミュレーションデータ生成（デモ・テスト用）"""
        seed = hash(f"{project_id}-{period}") % (2**31)
        rng = random.Random(seed)
        return AndpadMetrics(
            schedule_adherence_pct=round(rng.uniform(80, 100), 1),
            milestone_completion_pct=round(rng.uniform(75, 100), 1),
            delayed_tasks=rng.randint(0, 5),
            report_submission_pct=round(rng.uniform(85, 100), 1),
            photo_upload_count=rng.randint(20, 80),
            avg_response_hours=round(rng.uniform(0.5, 6.0), 1),
        )


class QualiteeClient:
    """クオリツ APIクライアント"""

    def __init__(self, api_key: str = ""):
        self.api_key = api_key
        self.base_url = "https://api.qualitee.jp/v1"

    def get_metrics(self, project_id: str, period: str) -> QualiteeMetrics:
        if not self.api_key:
            return self._simulate(project_id, period)
        if requests is None:
            print("Warning: requests not installed. Using simulation data.")
            return self._simulate(project_id, period)

        session = requests.Session()
        session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        })
        try:
            resp = session.get(
                f"{self.base_url}/projects/{project_id}/quality-metrics",
                params={"period": period},
            )
            resp.raise_for_status()
            data = resp.json()
            return QualiteeMetrics(
                inspection_pass_pct=data.get("inspection_pass_rate", 0),
                defect_count=data.get("defect_count", 0),
                critical_defect_count=data.get("critical_defects", 0),
                rework_pct=data.get("rework_rate", 0),
                safety_violation_count=data.get("safety_violations", 0),
                checklist_completion_pct=data.get("checklist_completion", 0),
            )
        except Exception as e:
            print(f"Qualitee API error: {e}. Falling back to simulation.")
            return self._simulate(project_id, period)

    def _simulate(self, project_id: str, period: str) -> QualiteeMetrics:
        """シミュレーションデータ生成"""
        seed = hash(f"q-{project_id}-{period}") % (2**31)
        rng = random.Random(seed)
        return QualiteeMetrics(
            inspection_pass_pct=round(rng.uniform(90, 100), 1),
            defect_count=rng.randint(0, 10),
            critical_defect_count=rng.randint(0, 2),
            rework_pct=round(rng.uniform(0, 8), 1),
            safety_violation_count=rng.randint(0, 3),
            checklist_completion_pct=round(rng.uniform(85, 100), 1),
        )


# ============================================================
# 識学評価エンジン
# ============================================================

class ShikigakuEvaluator:
    """
    識学の原則に基づく評価エンジン

    識学の核心:
    - 結果の定量化: すべてのKPIは数値で測定
    - 位置の明確化: 役割に紐づく明確な責任範囲
    - 曖昧さの排除: 達成/未達成の二値判定（strictモード）
    - 期限の設定: 評価期間内の結果のみで判断
    - 結果重視: プロセスではなく結果で評価
    """

    def __init__(self, strict: bool = False):
        self.strict = strict

    def evaluate(
        self,
        supervisor_name: str,
        site_name: str,
        project_id: str,
        period: str,
        andpad: AndpadMetrics,
        qualitee: QualiteeMetrics,
    ) -> EvaluationResult:

        result = EvaluationResult(
            supervisor_name=supervisor_name,
            site_name=site_name,
            project_id=project_id,
            period=period,
            evaluation_date=datetime.now().strftime("%Y-%m-%d"),
        )

        metrics_map = {"andpad": andpad, "qualitee": qualitee}

        for category, kpis in KPI_DEFINITIONS.items():
            category_weighted_sum = 0.0
            category_weight_total = 0.0

            for kpi_def in kpis:
                source_obj = metrics_map[kpi_def["source"]]
                actual = getattr(source_obj, kpi_def["field"])

                kpi_result = KPIResult(
                    name=kpi_def["name"],
                    category=category,
                    target=kpi_def["target"],
                    actual=float(actual),
                    unit=kpi_def["unit"],
                    weight=kpi_def["weight"],
                    lower_is_better=kpi_def["lower_is_better"],
                )

                kpi_result.score = self._calc_score(kpi_result)
                kpi_result.achieved = kpi_result.score >= 100.0

                result.kpi_results.append(kpi_result)
                category_weighted_sum += kpi_result.score * kpi_def["weight"]
                category_weight_total += kpi_def["weight"]

            if category_weight_total > 0:
                result.category_scores[category] = round(
                    category_weighted_sum / category_weight_total, 1
                )

        # 総合スコア = 重み付き平均
        total_weighted = sum(k.score * k.weight for k in result.kpi_results)
        total_weight = sum(k.weight for k in result.kpi_results)
        result.total_score = round(total_weighted / total_weight, 1) if total_weight else 0

        # グレード判定
        result.grade = self._determine_grade(result.total_score)

        # 強み・改善点・フィードバック生成
        result.strengths = self._find_strengths(result)
        result.improvements = self._find_improvements(result)
        result.feedback = self._generate_feedback(result)

        return result

    def _calc_score(self, kpi: KPIResult) -> float:
        """
        KPIスコア計算

        strictモード（識学式）: 目標達成=100, 未達成=0
        通常モード: 達成度に応じた比例スコア（0-100）
        """
        target = kpi.target
        actual = kpi.actual

        if kpi.lower_is_better:
            if target == 0:
                achieved = actual == 0
                if self.strict:
                    return 100.0 if achieved else 0.0
                return max(0, 100 - actual * 20) if not achieved else 100.0
            ratio = target / actual if actual > 0 else 100.0
            if self.strict:
                return 100.0 if actual <= target else 0.0
            return min(100.0, round(ratio * 100, 1))
        else:
            if target == 0:
                return 100.0 if actual >= 0 else 0.0
            ratio = actual / target
            if self.strict:
                return 100.0 if ratio >= 1.0 else 0.0
            return min(100.0, round(ratio * 100, 1))

    def _determine_grade(self, score: float) -> str:
        for threshold, grade, _ in GRADE_THRESHOLDS:
            if score >= threshold:
                return grade
        return "D"

    def _get_grade_label(self, score: float) -> str:
        for threshold, _, label in GRADE_THRESHOLDS:
            if score >= threshold:
                return label
        return "要指導"

    def _find_strengths(self, result: EvaluationResult) -> list:
        strengths = []
        for kpi in result.kpi_results:
            if kpi.score >= 95:
                strengths.append(f"{kpi.name}: {kpi.actual}{kpi.unit}（目標{kpi.target}{kpi.unit}）")
        return strengths[:5]

    def _find_improvements(self, result: EvaluationResult) -> list:
        improvements = []
        for kpi in sorted(result.kpi_results, key=lambda k: k.score):
            if kpi.score < 80:
                gap = ""
                if kpi.lower_is_better:
                    gap = f"目標{kpi.target}{kpi.unit}に対し{kpi.actual}{kpi.unit}"
                else:
                    gap = f"目標{kpi.target}{kpi.unit}に対し{kpi.actual}{kpi.unit}"
                improvements.append(f"{kpi.name}: {gap}")
        return improvements[:5]

    def _generate_feedback(self, result: EvaluationResult) -> list:
        """識学式フィードバック: 事実ベース、曖昧さなし"""
        feedback = []
        grade_label = self._get_grade_label(result.total_score)
        feedback.append(
            f"総合評価: {result.grade}（{grade_label}）- "
            f"スコア{result.total_score}/100"
        )

        # カテゴリ別フィードバック
        for cat, score in sorted(result.category_scores.items(), key=lambda x: x[1]):
            if score < 70:
                feedback.append(f"【要改善】{cat}: {score}点 - 目標水準を大幅に下回っています。具体的な改善計画を期限付きで提出してください。")
            elif score < 85:
                feedback.append(f"【改善余地】{cat}: {score}点 - 標準水準ですが、上位グレード達成には改善が必要です。")

        # 未達成KPIの具体的指摘
        unachieved = [k for k in result.kpi_results if not k.achieved]
        if unachieved:
            items = ", ".join(k.name for k in unachieved)
            feedback.append(f"未達成KPI: {items} - 次期までに目標達成が求められます。")

        if not unachieved:
            feedback.append("全KPI達成。現在の水準を維持してください。")

        return feedback


# ============================================================
# Markdown Report Generation
# ============================================================

def sanitize_filename(name: str) -> str:
    for ch in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']:
        name = name.replace(ch, '_')
    return name.strip()


def build_frontmatter(result: EvaluationResult) -> str:
    return f"""---
type: supervisor-evaluation
date: "{result.evaluation_date}"
supervisor: "{result.supervisor_name}"
project_id: "{result.project_id}"
site_name: "{result.site_name}"
evaluation_period: "{result.period}"
grade: "{result.grade}"
total_score: {result.total_score}
tags: [evaluation, supervisor, shikigaku]
status: confirmed
---"""


def build_kpi_table(kpis: list) -> str:
    lines = ["| KPI | 目標 | 実績 | 達成率 | スコア |"]
    lines.append("|-----|------|------|--------|--------|")
    for k in kpis:
        if k.lower_is_better and k.target == 0:
            achievement = "達成" if k.actual == 0 else "未達成"
        elif k.lower_is_better:
            achievement = f"{round(k.target / k.actual * 100, 1) if k.actual > 0 else 100}%"
        else:
            achievement = f"{round(k.actual / k.target * 100, 1) if k.target > 0 else 100}%"
        status = "○" if k.achieved else "×"
        lines.append(
            f"| {k.name} | {k.target}{k.unit} | {k.actual}{k.unit} | {achievement} | {k.score} {status} |"
        )
    return "\n".join(lines)


def build_evaluation_markdown(result: EvaluationResult) -> str:
    fm = build_frontmatter(result)
    grade_label = ""
    for t, g, l in GRADE_THRESHOLDS:
        if result.total_score >= t:
            grade_label = l
            break

    # KPIをカテゴリ別に分類
    by_category = {}
    for kpi in result.kpi_results:
        by_category.setdefault(kpi.category, []).append(kpi)

    category_source = {
        "工程管理": "ANDPAD",
        "品質管理": "クオリツ",
        "安全管理": "クオリツ",
        "報告・コミュニケーション": "ANDPAD",
    }

    sections = ""
    for cat in ["工程管理", "品質管理", "安全管理", "報告・コミュニケーション"]:
        kpis = by_category.get(cat, [])
        source = category_source.get(cat, "")
        cat_score = result.category_scores.get(cat, 0)
        sections += f"\n## {cat} ({source}) - {cat_score}点\n\n"
        sections += build_kpi_table(kpis) + "\n"

    strengths_md = "\n".join(f"- {s}" for s in result.strengths) if result.strengths else "- （特筆事項なし）"
    improvements_md = "\n".join(f"- {i}" for i in result.improvements) if result.improvements else "- （なし）"
    feedback_md = "\n".join(f"> {f}" for f in result.feedback)

    # 未達成KPIからアクションアイテムを自動生成
    actions = []
    for kpi in result.kpi_results:
        if not kpi.achieved:
            actions.append(f"- [ ] {kpi.name}の改善計画を策定する（目標: {kpi.target}{kpi.unit}）")
    if not actions:
        actions = ["- [ ] 現在の水準を維持するための施策を継続する"]

    actions_md = "\n".join(actions)

    return f"""{fm}

# 現場監督評価: {result.supervisor_name}（{result.period}）

## 評価概要
- **評価対象**: {result.supervisor_name}
- **現場名**: {result.site_name}
- **プロジェクトID**: {result.project_id}
- **評価期間**: {result.period}
- **評価日**: {result.evaluation_date}
- **総合スコア**: {result.total_score}/100
- **評価グレード**: {result.grade}（{grade_label}）

### カテゴリ別スコア
| カテゴリ | スコア | データソース |
|----------|--------|-------------|
| 工程管理 | {result.category_scores.get('工程管理', 0)}点 | ANDPAD |
| 品質管理 | {result.category_scores.get('品質管理', 0)}点 | クオリツ |
| 安全管理 | {result.category_scores.get('安全管理', 0)}点 | クオリツ |
| 報告・コミュニケーション | {result.category_scores.get('報告・コミュニケーション', 0)}点 | ANDPAD |
{sections}
## 強み
{strengths_md}

## 改善事項
{improvements_md}

## 識学フィードバック
{feedback_md}

## アクションアイテム
{actions_md}
"""


def save_evaluation(result: EvaluationResult) -> Path:
    EVALUATION_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = sanitize_filename(result.supervisor_name)
    filename = f"{result.period.replace('-', '')}_{safe_name}_評価.md"
    filepath = EVALUATION_DIR / filename

    counter = 1
    while filepath.exists():
        filename = f"{result.period.replace('-', '')}_{safe_name}_評価_{counter}.md"
        filepath = EVALUATION_DIR / filename
        counter += 1

    content = build_evaluation_markdown(result)
    filepath.write_text(content, encoding="utf-8")
    return filepath


# ============================================================
# List / Summary Commands
# ============================================================

def parse_frontmatter(content: str) -> dict:
    fm = {}
    match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    if match:
        for line in match.group(1).split("\n"):
            if ":" in line:
                key, _, value = line.partition(":")
                fm[key.strip()] = value.strip().strip('"').strip("'")
    return fm


def list_evaluations():
    if not EVALUATION_DIR.exists():
        print("評価データがありません。まず --evaluate で評価を実行してください。")
        return

    evals = sorted(EVALUATION_DIR.glob("*.md"), reverse=True)
    if not evals:
        print("評価データがありません。")
        return

    print(f"\n{'='*60}")
    print(f" 評価一覧（{len(evals)}件）")
    print(f"{'='*60}\n")

    for md in evals:
        content = md.read_text(encoding="utf-8", errors="replace")
        fm = parse_frontmatter(content)
        supervisor = fm.get("supervisor", "不明")
        period = fm.get("evaluation_period", "")
        grade = fm.get("grade", "")
        score = fm.get("total_score", "")
        site = fm.get("site_name", "")
        print(f"  {period}  {supervisor:12s}  グレード:{grade}  スコア:{score}  現場:{site}")
        print(f"         → {md.relative_to(VAULT_ROOT)}")
    print()


def show_summary(period: str):
    if not EVALUATION_DIR.exists():
        print("評価データがありません。")
        return

    evals = []
    for md in EVALUATION_DIR.glob("*.md"):
        content = md.read_text(encoding="utf-8", errors="replace")
        fm = parse_frontmatter(content)
        if fm.get("evaluation_period", "") == period:
            evals.append(fm)

    if not evals:
        print(f"期間 {period} の評価データがありません。")
        return

    print(f"\n{'='*60}")
    print(f" 評価サマリー: {period}")
    print(f"{'='*60}\n")

    # ランキング
    ranked = sorted(evals, key=lambda e: float(e.get("total_score", 0)), reverse=True)
    print("  順位  監督名          グレード  スコア  現場")
    print("  " + "-" * 55)
    for i, e in enumerate(ranked, 1):
        print(
            f"  {i:>3}.  {e.get('supervisor', ''):12s}  "
            f"{e.get('grade', ''):8s}  {e.get('total_score', ''):>6s}  "
            f"{e.get('site_name', '')}"
        )

    # 統計
    scores = [float(e.get("total_score", 0)) for e in evals]
    grade_counts = {}
    for e in evals:
        g = e.get("grade", "?")
        grade_counts[g] = grade_counts.get(g, 0) + 1

    print(f"\n  平均スコア: {sum(scores) / len(scores):.1f}")
    print(f"  最高: {max(scores):.1f} / 最低: {min(scores):.1f}")
    print(f"  グレード分布: {', '.join(f'{g}:{c}名' for g, c in sorted(grade_counts.items()))}")
    print()


# ============================================================
# Sample Data for Batch Evaluation
# ============================================================

SAMPLE_SUPERVISORS = [
    {"name": "田中太郎", "site": "Aマンション新築工事", "project_id": "PJ-001"},
    {"name": "鈴木一郎", "site": "B商業施設改修工事", "project_id": "PJ-002"},
    {"name": "佐藤花子", "site": "C戸建て分譲工事", "project_id": "PJ-003"},
    {"name": "高橋健二", "site": "D病院増築工事", "project_id": "PJ-004"},
    {"name": "山田美咲", "site": "E学校耐震補強工事", "project_id": "PJ-005"},
]


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="現場監督評価システム（識学 × ANDPAD × クオリツ）"
    )
    parser.add_argument("--evaluate", action="store_true", help="個別評価を実行")
    parser.add_argument("--evaluate-all", action="store_true", help="サンプル監督を一括評価")
    parser.add_argument("--list", action="store_true", help="保存済み評価の一覧")
    parser.add_argument("--summary", action="store_true", help="期間サマリー表示")
    parser.add_argument("--name", type=str, help="監督名")
    parser.add_argument("--site", type=str, help="現場名")
    parser.add_argument("--project-id", type=str, default="", help="ANDPADプロジェクトID")
    parser.add_argument("--period", type=str, help="評価期間（YYYY-MM）")
    parser.add_argument("--strict", action="store_true", help="識学厳格モード（二値評価）")
    parser.add_argument("--dry-run", action="store_true", help="保存せずに結果を表示")
    parser.add_argument("--json", action="store_true", help="JSON形式で出力")
    args = parser.parse_args()

    if not any([args.evaluate, args.evaluate_all, args.list, args.summary]):
        parser.print_help()
        sys.exit(1)

    if args.list:
        list_evaluations()
        return

    if args.summary:
        if not args.period:
            print("Error: --summary には --period が必要です")
            sys.exit(1)
        show_summary(args.period)
        return

    # Setup clients
    andpad_key = os.environ.get("ANDPAD_API_KEY", "")
    qualitee_key = os.environ.get("QUALITEE_API_KEY", "")
    andpad_client = AndpadClient(andpad_key)
    qualitee_client = QualiteeClient(qualitee_key)
    evaluator = ShikigakuEvaluator(strict=args.strict)

    if not andpad_key:
        print("Note: ANDPAD_API_KEY未設定 → シミュレーションデータを使用")
    if not qualitee_key:
        print("Note: QUALITEE_API_KEY未設定 → シミュレーションデータを使用")

    if args.strict:
        print("Mode: 識学厳格モード（達成/未達成の二値評価）")
    print()

    # Build evaluation targets
    targets = []
    if args.evaluate:
        if not args.name or not args.site or not args.period:
            print("Error: --evaluate には --name, --site, --period が必要です")
            sys.exit(1)
        targets.append({
            "name": args.name,
            "site": args.site,
            "project_id": args.project_id or f"PJ-{hash(args.name) % 1000:03d}",
        })
    elif args.evaluate_all:
        if not args.period:
            print("Error: --evaluate-all には --period が必要です")
            sys.exit(1)
        targets = SAMPLE_SUPERVISORS

    # Execute evaluations
    for target in targets:
        print(f"評価中: {target['name']}（{target['site']}）...")

        andpad_metrics = andpad_client.get_metrics(target["project_id"], args.period)
        qualitee_metrics = qualitee_client.get_metrics(target["project_id"], args.period)

        result = evaluator.evaluate(
            supervisor_name=target["name"],
            site_name=target["site"],
            project_id=target["project_id"],
            period=args.period,
            andpad=andpad_metrics,
            qualitee=qualitee_metrics,
        )

        if args.json:
            out = {
                "supervisor": result.supervisor_name,
                "site": result.site_name,
                "period": result.period,
                "grade": result.grade,
                "total_score": result.total_score,
                "category_scores": result.category_scores,
                "kpis": [asdict(k) for k in result.kpi_results],
                "strengths": result.strengths,
                "improvements": result.improvements,
                "feedback": result.feedback,
            }
            print(json.dumps(out, ensure_ascii=False, indent=2))
        else:
            print(f"\n  {'─'*50}")
            print(f"  {result.supervisor_name} | {result.site_name}")
            print(f"  グレード: {result.grade} | スコア: {result.total_score}/100")
            print(f"  {'─'*50}")
            for cat, score in result.category_scores.items():
                bar_len = int(score / 5)
                bar = "█" * bar_len + "░" * (20 - bar_len)
                print(f"  {cat:16s} {bar} {score}")
            if result.improvements:
                print(f"\n  改善事項:")
                for imp in result.improvements:
                    print(f"    → {imp}")
            print()

        if not args.dry_run:
            path = save_evaluation(result)
            print(f"  保存: {path.relative_to(VAULT_ROOT)}")
        print()

    # Show summary if batch
    if args.evaluate_all and not args.dry_run:
        print("=" * 60)
        show_summary(args.period)


if __name__ == "__main__":
    main()
