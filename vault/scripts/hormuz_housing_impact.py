#!/usr/bin/env python3
"""
ホルムズ海峡封鎖 住宅業界経済影響シミュレーター
- 平松建築の経営判断用ダッシュボード
- 住まい手への情報発信（YouTube台本生成）
- ナフサショックによる建材価格高騰シミュレーション

Usage:
  python hormuz_housing_impact.py --scenario partial --duration 90
  python hormuz_housing_impact.py --scenario full --duration 180 --save-to-vault
  python hormuz_housing_impact.py --youtube --month 2026-06
"""

import argparse
import json
import math
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

VAULT_ROOT = Path(__file__).resolve().parent.parent

# ============================================================
# 基礎データ定義
# ============================================================

# 原油・ナフサ基準価格
BASELINE = {
    "crude_oil_usd_barrel": 75.0,
    "naphtha_usd_ton": 620.0,
    "exchange_rate": 155.0,  # USD/JPY
    "hormuz_share_japan_oil": 0.88,  # 日本の石油輸入のうちホルムズ依存
    "hormuz_share_japan_lng": 0.20,
    "japan_spr_days": 145,  # 国家備蓄+民間備蓄（日数）
}

# 封鎖シナリオ定義
SCENARIOS = {
    "partial": {
        "label": "部分封鎖（船舶検査・遅延）",
        "supply_cut_rate": 0.30,
        "oil_price_multiplier": 1.6,
        "naphtha_premium": 1.8,
        "duration_label": "部分的な航行制限",
        "probability": "中〜高",
    },
    "full": {
        "label": "完全封鎖",
        "supply_cut_rate": 0.88,
        "oil_price_multiplier": 2.8,
        "naphtha_premium": 3.2,
        "duration_label": "全面通航停止",
        "probability": "低〜中",
    },
    "escalation": {
        "label": "軍事衝突エスカレーション",
        "supply_cut_rate": 0.95,
        "oil_price_multiplier": 4.0,
        "naphtha_premium": 4.5,
        "duration_label": "軍事衝突による長期遮断",
        "probability": "低",
    },
}

# ----------------------------------------------------------
# 住宅建材：ナフサ・石油依存マッピング
# 一棟あたり標準使用量と原価（木造注文住宅 延床35坪想定）
# ----------------------------------------------------------
HOUSING_MATERIALS = {
    "断熱材（発泡ウレタン・EPS・XPS）": {
        "baseline_cost": 850000,
        "oil_dependency": 0.85,  # ナフサ由来率
        "category": "石油化学製品",
        "supply_risk": "高",
        "description": "原料のほぼ全量がナフサ由来。代替困難。",
    },
    "塩ビ管・配管部材（PVC）": {
        "baseline_cost": 280000,
        "oil_dependency": 0.90,
        "category": "石油化学製品",
        "supply_risk": "高",
        "description": "給排水の基幹部材。ナフサ→エチレン→塩ビの流れ。",
    },
    "塗料・シーリング材": {
        "baseline_cost": 350000,
        "oil_dependency": 0.70,
        "category": "石油化学製品",
        "supply_risk": "高",
        "description": "溶剤・樹脂ともに石油由来成分が多い。",
    },
    "接着剤（フローリング・合板用）": {
        "baseline_cost": 180000,
        "oil_dependency": 0.75,
        "category": "石油化学製品",
        "supply_risk": "中",
        "description": "ウレタン系・エポキシ系ともにナフサ原料。",
    },
    "サイディング（窯業系）": {
        "baseline_cost": 1200000,
        "oil_dependency": 0.25,
        "category": "複合材",
        "supply_risk": "中",
        "description": "主成分はセメントだが、焼成エネルギーと塗装面に影響。",
    },
    "屋根材（アスファルトシングル・防水シート）": {
        "baseline_cost": 600000,
        "oil_dependency": 0.60,
        "category": "石油化学製品",
        "supply_risk": "高",
        "description": "アスファルト・防水シートは石油精製の副産物。",
    },
    "電線・配線部材": {
        "baseline_cost": 220000,
        "oil_dependency": 0.40,
        "category": "複合材",
        "supply_risk": "中",
        "description": "被覆材がPVC。銅線自体も精錬エネルギーに影響。",
    },
    "木材（構造材・羽柄材）": {
        "baseline_cost": 3500000,
        "oil_dependency": 0.15,
        "category": "天然素材",
        "supply_risk": "低〜中",
        "description": "素材自体は非石油だが、乾燥・加工・運搬に燃料コスト。",
    },
    "基礎コンクリート・鉄筋": {
        "baseline_cost": 2200000,
        "oil_dependency": 0.20,
        "category": "鉱物系",
        "supply_risk": "中",
        "description": "セメント焼成に重油、鉄筋は電炉だが電力コスト上昇。",
    },
    "住宅設備（キッチン・バス・トイレ）": {
        "baseline_cost": 3000000,
        "oil_dependency": 0.35,
        "category": "複合材",
        "supply_risk": "中",
        "description": "樹脂パーツ・FRP浴槽・パッキン類に石油製品。",
    },
    "ビニルクロス（壁紙）": {
        "baseline_cost": 400000,
        "oil_dependency": 0.80,
        "category": "石油化学製品",
        "supply_risk": "高",
        "description": "PVC（ポリ塩化ビニル）が主原料。ほぼナフサ依存。",
    },
    "クッションフロア・長尺シート": {
        "baseline_cost": 250000,
        "oil_dependency": 0.85,
        "category": "石油化学製品",
        "supply_risk": "高",
        "description": "PVC系床材。ナフサ直撃品目。",
    },
    "運搬・重機燃料": {
        "baseline_cost": 450000,
        "oil_dependency": 1.00,
        "category": "燃料",
        "supply_risk": "高",
        "description": "資材運搬・クレーン・重機の軽油・ガソリン。",
    },
}

# 平松建築 事業パラメータ（推定値 - 調整可能）
HIRAMATSU_PARAMS = {
    "annual_houses": 60,  # 年間着工棟数
    "avg_contract_price": 30000000,  # 平均請負金額
    "avg_material_cost": 13500000,  # 平均建材原価/棟
    "gross_margin_rate": 0.28,  # 粗利率
    "contract_to_start_months": 4,  # 契約から着工までの平均月数
    "fixed_cost_monthly": 12000000,  # 月間固定費
    "employee_count": 45,
    "region": "静岡県浜松市",
    "strength": "高気密高断熱住宅",  # → 断熱材依存度が特に高い
}

# 住まい手影響パラメータ
HOMEOWNER_IMPACT = {
    "avg_new_home_price": 35000000,
    "avg_renovation_price": 8000000,
    "monthly_energy_cost": 18000,  # 平均的な光熱費
    "mortgage_rate_current": 0.015,  # 変動金利
    "oil_to_electricity_pass": 0.25,  # 原油高→電気代転嫁率
    "oil_to_gas_pass": 0.40,  # 原油高→ガス代転嫁率
}


# ============================================================
# シミュレーションエンジン
# ============================================================

def calc_oil_price(scenario_key, duration_days):
    """封鎖シナリオに応じた原油・ナフサ価格推移を計算"""
    sc = SCENARIOS[scenario_key]
    phases = []
    base_oil = BASELINE["crude_oil_usd_barrel"]
    base_naphtha = BASELINE["naphtha_usd_ton"]

    for day in range(1, duration_days + 1):
        # 初期急騰（1-14日）→ 高止まり → SPR放出で若干緩和
        if day <= 14:
            ramp = day / 14.0
            oil_mult = 1.0 + (sc["oil_price_multiplier"] - 1.0) * ramp
            naphtha_mult = 1.0 + (sc["naphtha_premium"] - 1.0) * ramp
        elif day <= BASELINE["japan_spr_days"]:
            # SPR放出期間中は微減
            decay = 0.05 * ((day - 14) / (BASELINE["japan_spr_days"] - 14))
            oil_mult = sc["oil_price_multiplier"] - decay
            naphtha_mult = sc["naphtha_premium"] - decay * 0.5
        else:
            # SPR枯渇後は再上昇
            overshoot = 0.3 * ((day - BASELINE["japan_spr_days"]) / 30)
            oil_mult = sc["oil_price_multiplier"] + min(overshoot, 0.8)
            naphtha_mult = sc["naphtha_premium"] + min(overshoot * 1.2, 1.0)

        phases.append({
            "day": day,
            "oil_usd": round(base_oil * oil_mult, 1),
            "oil_mult": round(oil_mult, 2),
            "naphtha_usd": round(base_naphtha * naphtha_mult, 1),
            "naphtha_mult": round(naphtha_mult, 2),
        })

    return phases


def calc_material_impact(scenario_key, duration_days):
    """建材別の価格上昇を計算"""
    sc = SCENARIOS[scenario_key]
    # ナフサプレミアムの安定期値を使用
    naphtha_mult = sc["naphtha_premium"]

    results = []
    total_baseline = 0
    total_shocked = 0

    for name, mat in HOUSING_MATERIALS.items():
        price_increase_rate = 1.0 + (naphtha_mult - 1.0) * mat["oil_dependency"]
        # 長期化による追加上昇（供給不安・在庫枯渇）
        if duration_days > 90:
            price_increase_rate *= 1.0 + 0.10 * min((duration_days - 90) / 90, 1.0)

        shocked_cost = int(mat["baseline_cost"] * price_increase_rate)
        increase_amount = shocked_cost - mat["baseline_cost"]

        results.append({
            "name": name,
            "category": mat["category"],
            "baseline_cost": mat["baseline_cost"],
            "shocked_cost": shocked_cost,
            "increase_rate": round((price_increase_rate - 1.0) * 100, 1),
            "increase_amount": increase_amount,
            "oil_dependency": mat["oil_dependency"],
            "supply_risk": mat["supply_risk"],
            "description": mat["description"],
        })
        total_baseline += mat["baseline_cost"]
        total_shocked += shocked_cost

    results.sort(key=lambda x: x["increase_rate"], reverse=True)
    return results, total_baseline, total_shocked


def calc_hiramatsu_impact(scenario_key, duration_days, material_results, total_baseline, total_shocked):
    """平松建築への事業影響を計算"""
    p = HIRAMATSU_PARAMS
    sc = SCENARIOS[scenario_key]

    cost_increase_per_house = total_shocked - total_baseline
    cost_increase_rate = (total_shocked / total_baseline - 1.0) * 100

    # 高気密高断熱 → 断熱材比率が高いため追加影響
    insulation_extra = 0
    for m in material_results:
        if "断熱" in m["name"]:
            insulation_extra = int(m["increase_amount"] * 0.3)
            break
    cost_increase_per_house += insulation_extra

    # 年間影響
    affected_months = min(duration_days / 30, 12)
    affected_houses = int(p["annual_houses"] * affected_months / 12)

    # 契約済み未着工の逸失利益（固定価格契約分）
    contracted_backlog = int(p["annual_houses"] * p["contract_to_start_months"] / 12)
    backlog_loss = contracted_backlog * cost_increase_per_house

    # 新規受注への影響（価格転嫁 vs 需要減）
    price_pass_through = 0.60  # 60%しか転嫁できない想定
    unrecovered_per_house = int(cost_increase_per_house * (1 - price_pass_through))
    new_contract_price = p["avg_contract_price"] + int(cost_increase_per_house * price_pass_through)

    # 需要減退（価格上昇による）
    price_elasticity = -0.8
    demand_change_rate = price_elasticity * (cost_increase_per_house * price_pass_through / p["avg_contract_price"])
    demand_change_houses = int(p["annual_houses"] * demand_change_rate * affected_months / 12)

    # 粗利影響
    normal_gross_profit = p["avg_contract_price"] * p["gross_margin_rate"]
    shocked_gross_profit = normal_gross_profit - unrecovered_per_house
    gross_margin_shocked = shocked_gross_profit / new_contract_price

    # 資金繰り影響
    monthly_cash_impact = int(
        (contracted_backlog * cost_increase_per_house / max(p["contract_to_start_months"], 1))
        + p["fixed_cost_monthly"] * 0.05 * sc["oil_price_multiplier"]
    )

    return {
        "cost_increase_per_house": cost_increase_per_house,
        "cost_increase_rate": round(cost_increase_rate, 1),
        "insulation_extra_note": f"高断熱仕様による追加影響: +{insulation_extra:,}円/棟",
        "affected_houses": affected_houses,
        "contracted_backlog": contracted_backlog,
        "backlog_loss": backlog_loss,
        "unrecovered_per_house": unrecovered_per_house,
        "new_contract_price": new_contract_price,
        "demand_change_houses": demand_change_houses,
        "normal_gross_margin": round(p["gross_margin_rate"] * 100, 1),
        "shocked_gross_margin": round(gross_margin_shocked * 100, 1),
        "monthly_cash_impact": monthly_cash_impact,
        "annual_profit_impact": int(
            backlog_loss
            + affected_houses * unrecovered_per_house
            + abs(demand_change_houses) * normal_gross_profit
        ),
    }


def calc_homeowner_impact(scenario_key, duration_days):
    """住まい手への影響を計算"""
    sc = SCENARIOS[scenario_key]
    ho = HOMEOWNER_IMPACT

    oil_mult = sc["oil_price_multiplier"]

    # 光熱費上昇
    electricity_increase = (oil_mult - 1.0) * ho["oil_to_electricity_pass"]
    gas_increase = (oil_mult - 1.0) * ho["oil_to_gas_pass"]
    monthly_energy_increase = int(ho["monthly_energy_cost"] * (
        electricity_increase * 0.6 + gas_increase * 0.4
    ))
    annual_energy_increase = monthly_energy_increase * 12

    # 新築価格上昇
    material_share = 0.40
    new_home_increase_rate = (sc["naphtha_premium"] - 1.0) * material_share * 0.5
    new_home_increase = int(ho["avg_new_home_price"] * new_home_increase_rate)

    # リフォーム価格上昇（建材比率が高い）
    reno_material_share = 0.55
    reno_increase_rate = (sc["naphtha_premium"] - 1.0) * reno_material_share * 0.6
    reno_increase = int(ho["avg_renovation_price"] * reno_increase_rate)

    # 金利影響（インフレ→利上げ圧力）
    rate_increase = min((oil_mult - 1.0) * 0.003, 0.01)
    new_rate = ho["mortgage_rate_current"] + rate_increase
    # 3500万円35年ローンでの月額差
    loan = 35000000
    term = 35 * 12
    old_monthly = loan * (ho["mortgage_rate_current"]/12) / (1 - (1+ho["mortgage_rate_current"]/12)**(-term))
    new_monthly = loan * (new_rate/12) / (1 - (1+new_rate/12)**(-term))
    mortgage_monthly_increase = int(new_monthly - old_monthly)

    # ガソリン代
    gasoline_base = 170  # 円/L
    gasoline_shocked = int(gasoline_base * oil_mult)
    monthly_gas_cost_increase = int((gasoline_shocked - gasoline_base) * 60)  # 月60L想定

    return {
        "monthly_energy_increase": monthly_energy_increase,
        "annual_energy_increase": annual_energy_increase,
        "new_home_increase": new_home_increase,
        "new_home_increase_rate": round(new_home_increase_rate * 100, 1),
        "reno_increase": reno_increase,
        "reno_increase_rate": round(reno_increase_rate * 100, 1),
        "mortgage_rate_current": ho["mortgage_rate_current"] * 100,
        "mortgage_rate_shocked": round(new_rate * 100, 2),
        "mortgage_monthly_increase": mortgage_monthly_increase,
        "gasoline_base": gasoline_base,
        "gasoline_shocked": gasoline_shocked,
        "monthly_gas_cost_increase": monthly_gas_cost_increase,
        "total_monthly_household_impact": (
            monthly_energy_increase + mortgage_monthly_increase + monthly_gas_cost_increase
        ),
    }


def calc_mitigation_strategies(scenario_key, hiramatsu_impact):
    """緩和策と効果を算出"""
    loss = hiramatsu_impact["annual_profit_impact"]

    strategies = [
        {
            "name": "資材の早期一括仕入れ（3ヶ月分先行発注）",
            "category": "調達",
            "reduction_rate": 0.25,
            "reduction_amount": int(loss * 0.25),
            "cost": 5000000,
            "timeline": "即時",
            "difficulty": "中",
            "detail": "主要建材（断熱材・塩ビ管・塗料）を3ヶ月分先行発注。倉庫コスト発生するが価格高騰リスクをヘッジ。",
        },
        {
            "name": "契約書への価格変動条項（スライド条項）追加",
            "category": "契約",
            "reduction_rate": 0.30,
            "reduction_amount": int(loss * 0.30),
            "cost": 0,
            "timeline": "次回契約から",
            "difficulty": "低",
            "detail": "新規契約に原材料費スライド条項を盛り込み、一定以上の資材高騰時は契約金額を調整可能にする。",
        },
        {
            "name": "代替建材の検討・認定取得",
            "category": "技術",
            "reduction_rate": 0.15,
            "reduction_amount": int(loss * 0.15),
            "cost": 2000000,
            "timeline": "3〜6ヶ月",
            "difficulty": "高",
            "detail": "セルロースファイバー断熱材、珪藻土塗壁、天然素材系接着剤など石油依存度の低い代替品を評価・採用。",
        },
        {
            "name": "地域木材（天竜材）活用比率の拡大",
            "category": "調達",
            "reduction_rate": 0.10,
            "reduction_amount": int(loss * 0.10),
            "cost": 1000000,
            "timeline": "1〜3ヶ月",
            "difficulty": "低",
            "detail": "地元天竜材の活用を拡大し、輸送コスト削減と石油由来建材の使用量削減を同時実現。",
        },
        {
            "name": "太陽光+蓄電池の標準提案で光熱費メリット訴求",
            "category": "営業",
            "reduction_rate": 0.05,
            "reduction_amount": int(loss * 0.05),
            "cost": 0,
            "timeline": "即時",
            "difficulty": "低",
            "detail": "エネルギー価格高騰を逆手に取り、ZEH・太陽光・蓄電池のメリットを強調した営業展開。受注維持に貢献。",
        },
        {
            "name": "施工スケジュールの前倒し・集約化",
            "category": "施工",
            "reduction_rate": 0.08,
            "reduction_amount": int(loss * 0.08),
            "cost": 500000,
            "timeline": "即時",
            "difficulty": "中",
            "detail": "現場の稼働効率を上げ、重機・運搬の燃料消費を削減。複数現場の資材搬入をまとめて効率化。",
        },
        {
            "name": "住まい手への情報発信（YouTube・SNS）",
            "category": "広報",
            "reduction_rate": 0.05,
            "reduction_amount": int(loss * 0.05),
            "cost": 100000,
            "timeline": "即時",
            "difficulty": "低",
            "detail": "ナフサショックの住宅への影響を分かりやすく発信。「今建てる理由」「備える家づくり」のブランディング強化。",
        },
    ]
    return strategies


# ============================================================
# レポート生成
# ============================================================

def format_currency(n):
    if abs(n) >= 100000000:
        return f"{n/100000000:.1f}億円"
    elif abs(n) >= 10000:
        return f"{n/10000:,.0f}万円"
    else:
        return f"{n:,}円"


def generate_bar(value, max_value, width=20):
    filled = int(width * min(value / max_value, 1.0))
    return "█" * filled + "░" * (width - filled)


def generate_report(scenario_key, duration_days, prices, materials, total_base, total_shocked,
                    hiramatsu, homeowner, strategies, report_date=None):
    """Markdownレポートを生成"""
    sc = SCENARIOS[scenario_key]
    if report_date is None:
        report_date = datetime.now().strftime("%Y-%m-%d")

    peak_oil = max(p["oil_usd"] for p in prices)
    peak_naphtha = max(p["naphtha_usd"] for p in prices)

    lines = []
    lines.append("---")
    lines.append("type: project")
    lines.append(f"date: {report_date}")
    lines.append("tags: [ホルムズ海峡, ナフサショック, 住宅業界, 経済影響, 平松建築]")
    lines.append("---")
    lines.append("")
    lines.append("# ホルムズ海峡封鎖 住宅業界影響レポート")
    lines.append("")
    lines.append(f"> 生成日: {report_date} ｜ シナリオ: **{sc['label']}** ｜ 想定期間: **{duration_days}日間** ｜ 発生確率: {sc['probability']}")
    lines.append("")

    # セクション1: エグゼクティブサマリー
    lines.append("## 📊 エグゼクティブサマリー")
    lines.append("")
    lines.append("| 指標 | 値 |")
    lines.append("|---|---|")
    lines.append(f"| 原油価格ピーク | ${peak_oil}/バレル（通常比 {max(p['oil_mult'] for p in prices)}倍） |")
    lines.append(f"| ナフサ価格ピーク | ${peak_naphtha}/トン（通常比 {max(p['naphtha_mult'] for p in prices)}倍） |")
    lines.append(f"| 一棟あたり建材コスト増 | **{format_currency(hiramatsu['cost_increase_per_house'])}**（+{hiramatsu['cost_increase_rate']}%） |")
    lines.append(f"| 平松建築 年間利益影響 | **▲{format_currency(hiramatsu['annual_profit_impact'])}** |")
    lines.append(f"| 住まい手 月額負担増 | **+{format_currency(homeowner['total_monthly_household_impact'])}/月** |")
    lines.append(f"| 新築価格上昇 | +{format_currency(homeowner['new_home_increase'])}（+{homeowner['new_home_increase_rate']}%） |")
    lines.append("")

    # セクション2: 原油・ナフサ価格推移
    lines.append("## 📈 原油・ナフサ価格推移シミュレーション")
    lines.append("")
    lines.append("| 経過日数 | 原油 (USD/バレル) | 倍率 | ナフサ (USD/トン) | 倍率 |")
    lines.append("|---:|---:|---:|---:|---:|")
    checkpoints = [1, 7, 14, 30, 60, 90, 120, 150, 180]
    for cp in checkpoints:
        if cp <= duration_days:
            p = prices[cp - 1]
            lines.append(f"| {p['day']}日目 | ${p['oil_usd']} | ×{p['oil_mult']} | ${p['naphtha_usd']} | ×{p['naphtha_mult']} |")
    lines.append("")

    # セクション3: 建材別影響
    lines.append("## 🏗️ 建材別価格影響（1棟あたり）")
    lines.append("")
    lines.append(f"> 想定: 木造注文住宅 延床35坪 ｜ 通常建材費合計: {format_currency(total_base)} → **{format_currency(total_shocked)}**")
    lines.append("")
    lines.append("| 建材 | 通常原価 | 高騰後 | 上昇率 | 石油依存度 | リスク | 影響度 |")
    lines.append("|---|---:|---:|---:|---:|---|---|")
    max_rate = max(m["increase_rate"] for m in materials)
    for m in materials:
        bar = generate_bar(m["increase_rate"], max_rate, 10)
        lines.append(
            f"| {m['name']} | {format_currency(m['baseline_cost'])} | {format_currency(m['shocked_cost'])} "
            f"| +{m['increase_rate']}% | {int(m['oil_dependency']*100)}% | {m['supply_risk']} | {bar} |"
        )
    lines.append("")

    # 石油依存度マップ
    lines.append("### 石油化学製品サプライチェーン")
    lines.append("")
    lines.append("```")
    lines.append("原油 → ナフサ → エチレン / プロピレン")
    lines.append("                    │              │")
    lines.append("                    ├→ ポリエチレン → 防湿シート・断熱材")
    lines.append("                    ├→ 塩化ビニル  → 配管・壁紙・床材")
    lines.append("                    ├→ ポリウレタン → 断熱材・接着剤・シーリング")
    lines.append("                    ├→ ポリスチレン → 断熱材（EPS・XPS）")
    lines.append("                    ├→ アクリル樹脂 → 塗料・浴槽")
    lines.append("                    └→ エポキシ樹脂 → 接着剤・防水材")
    lines.append("```")
    lines.append("")

    # セクション4: 平松建築への影響
    lines.append("## 🏠 平松建築への事業影響")
    lines.append("")
    lines.append(f"**前提条件**: 年間{HIRAMATSU_PARAMS['annual_houses']}棟 ｜ 平均請負額{format_currency(HIRAMATSU_PARAMS['avg_contract_price'])} ｜ 粗利率{HIRAMATSU_PARAMS['gross_margin_rate']*100}% ｜ {HIRAMATSU_PARAMS['strength']}")
    lines.append("")
    lines.append("### 損益影響")
    lines.append("")
    lines.append("| 項目 | 影響額 |")
    lines.append("|---|---:|")
    lines.append(f"| 一棟あたりコスト増 | +{format_currency(hiramatsu['cost_increase_per_house'])} |")
    lines.append(f"| {hiramatsu['insulation_extra_note']} | （上記に含む） |")
    lines.append(f"| 契約済み未着工分の損失（{hiramatsu['contracted_backlog']}棟） | ▲{format_currency(hiramatsu['backlog_loss'])} |")
    lines.append(f"| 価格転嫁できない分/棟 | ▲{format_currency(hiramatsu['unrecovered_per_house'])} |")
    lines.append(f"| 需要減退による受注減 | {hiramatsu['demand_change_houses']}棟 |")
    lines.append(f"| 粗利率変動 | {hiramatsu['normal_gross_margin']}% → **{hiramatsu['shocked_gross_margin']}%** |")
    lines.append(f"| 月次キャッシュフロー影響 | ▲{format_currency(hiramatsu['monthly_cash_impact'])}/月 |")
    lines.append(f"| **年間利益影響合計** | **▲{format_currency(hiramatsu['annual_profit_impact'])}** |")
    lines.append("")

    # 高断熱住宅特有のリスク
    lines.append("### ⚠️ 高気密高断熱住宅 特有のリスク")
    lines.append("")
    lines.append("平松建築は高気密高断熱を強みとしているため、以下の追加リスクがあります：")
    lines.append("")
    lines.append("- **断熱材使用量が一般住宅の1.5〜2倍** → ナフサ高騰の影響が増幅")
    lines.append("- **発泡ウレタン吹付** → 原料MDI（ジフェニルメタンジイソシアネート）もナフサ由来")
    lines.append("- **高性能サッシのガスケット・パッキン** → 合成ゴム（石油由来）")
    lines.append("- **気密シート・防湿フィルム** → ポリエチレン（ナフサ→エチレン）")
    lines.append("")
    lines.append("**逆にチャンスとなる点：**")
    lines.append("- エネルギー価格高騰で「光熱費が安い家」の価値が上昇")
    lines.append("- ZEH・太陽光・蓄電池の経済メリットが拡大")
    lines.append("- 「エネルギーに左右されない暮らし」という訴求力の強化")
    lines.append("")

    # セクション5: 住まい手への影響
    lines.append("## 👨‍👩‍👧‍👦 住まい手（お客様）への影響")
    lines.append("")
    lines.append("### 家計への月額影響")
    lines.append("")
    lines.append("| 項目 | 月額増加 |")
    lines.append("|---|---:|")
    lines.append(f"| 光熱費（電気・ガス） | +{format_currency(homeowner['monthly_energy_increase'])} |")
    lines.append(f"| ガソリン代（月60L想定） | +{format_currency(homeowner['monthly_gas_cost_increase'])} |")
    lines.append(f"| 住宅ローン（金利上昇時） | +{format_currency(homeowner['mortgage_monthly_increase'])} |")
    lines.append(f"| **月額合計** | **+{format_currency(homeowner['total_monthly_household_impact'])}** |")
    lines.append(f"| **年額換算** | **+{format_currency(homeowner['total_monthly_household_impact'] * 12)}** |")
    lines.append("")
    lines.append("### 住宅取得コストへの影響")
    lines.append("")
    lines.append(f"- 新築住宅: +**{format_currency(homeowner['new_home_increase'])}**（+{homeowner['new_home_increase_rate']}%）")
    lines.append(f"- リフォーム: +**{format_currency(homeowner['reno_increase'])}**（+{homeowner['reno_increase_rate']}%）")
    lines.append(f"- ガソリン: {homeowner['gasoline_base']}円/L → **{homeowner['gasoline_shocked']}円/L**")
    lines.append(f"- 住宅ローン金利: {homeowner['mortgage_rate_current']}% → **{homeowner['mortgage_rate_shocked']}%**")
    lines.append("")

    # セクション6: 緩和策
    lines.append("## 🛡️ 対策・緩和策")
    lines.append("")
    total_reduction = sum(s["reduction_amount"] for s in strategies)
    lines.append(f"> 全策実施時の想定損失軽減額: **{format_currency(total_reduction)}**（損失の{int(sum(s['reduction_rate'] for s in strategies)*100)}%カバー）")
    lines.append("")
    lines.append("| # | 対策 | 分類 | 軽減額 | コスト | 実行時期 | 難易度 |")
    lines.append("|---|---|---|---:|---:|---|---|")
    for i, s in enumerate(strategies, 1):
        lines.append(
            f"| {i} | {s['name']} | {s['category']} | {format_currency(s['reduction_amount'])} "
            f"| {format_currency(s['cost'])} | {s['timeline']} | {s['difficulty']} |"
        )
    lines.append("")
    for i, s in enumerate(strategies, 1):
        lines.append(f"**{i}. {s['name']}**")
        lines.append(f"> {s['detail']}")
        lines.append("")

    # セクション7: YouTube台本ポイント
    lines.append("## 🎬 YouTube発信用ポイント")
    lines.append("")
    lines.append("### 住まい手に伝えるべき3つのポイント")
    lines.append("")
    lines.append(f"1. **家を建てるコストが{homeowner['new_home_increase_rate']}%上がる可能性**")
    lines.append(f"   - 3500万円の家が+{format_currency(homeowner['new_home_increase'])}に")
    lines.append(f"   - 断熱材・配管・塗料…家の見えない部分が実は石油でできている")
    lines.append("")
    lines.append(f"2. **毎月の生活コストが+{format_currency(homeowner['total_monthly_household_impact'])}増える**")
    lines.append(f"   - 光熱費+{format_currency(homeowner['monthly_energy_increase'])}、ガソリン+{format_currency(homeowner['monthly_gas_cost_increase'])}")
    lines.append(f"   - 年間で+{format_currency(homeowner['total_monthly_household_impact'] * 12)}の負担増")
    lines.append("")
    lines.append("3. **今からできる備え**")
    lines.append("   - 高断熱住宅＋太陽光＋蓄電池で「エネルギー自給」")
    lines.append("   - 光熱費が上がるほど、高性能住宅の価値が上がる")
    lines.append("   - 建材価格が上がる前の計画が有利")
    lines.append("")

    lines.append("### 台本構成案（10〜15分動画）")
    lines.append("")
    lines.append("```")
    lines.append("0:00 - オープニング「ホルムズ海峡で何が起きている？」")
    lines.append("1:00 - ナフサショックとは？（図解）")
    lines.append("3:00 - あなたの家は石油でできている（建材の石油依存度）")
    lines.append("5:00 - 家を建てるコストはこう変わる（具体的数字）")
    lines.append("7:00 - 毎月の生活費への影響（光熱費・ガソリン）")
    lines.append("9:00 - 備える家づくり3つのポイント")
    lines.append("12:00 - まとめ・次回予告")
    lines.append("```")
    lines.append("")

    # セクション8: 前提条件・免責
    lines.append("## 📝 前提条件・注意事項")
    lines.append("")
    lines.append("- 本レポートはシミュレーションに基づく推計値であり、実際の影響を保証するものではありません")
    lines.append(f"- 原油基準価格: ${BASELINE['crude_oil_usd_barrel']}/バレル、為替: {BASELINE['exchange_rate']}円/ドル")
    lines.append(f"- 日本のSPR（戦略石油備蓄）: {BASELINE['japan_spr_days']}日分")
    lines.append("- 建材価格は2025年後半の標準的な市場価格を基準としています")
    lines.append("- 平松建築のパラメータは一般的な地域工務店の推定値です（要調整）")
    lines.append("")
    lines.append(f"*Generated by hormuz_housing_impact.py | {report_date}*")

    return "\n".join(lines)


# ============================================================
# コンソール出力
# ============================================================

def print_summary(scenario_key, duration_days, materials, total_base, total_shocked,
                  hiramatsu, homeowner, strategies):
    sc = SCENARIOS[scenario_key]

    print("\n" + "=" * 70)
    print(f"  ホルムズ海峡封鎖 住宅業界影響シミュレーション")
    print(f"  シナリオ: {sc['label']} ｜ 期間: {duration_days}日間")
    print("=" * 70)

    print(f"\n【建材コスト影響（1棟あたり）】")
    print(f"  通常建材費:   {format_currency(total_base)}")
    print(f"  高騰後建材費: {format_currency(total_shocked)}")
    print(f"  差額:         +{format_currency(total_shocked - total_base)}（+{hiramatsu['cost_increase_rate']}%）")

    print(f"\n  上昇率TOP5:")
    for m in materials[:5]:
        bar = generate_bar(m["increase_rate"], materials[0]["increase_rate"], 15)
        print(f"    {m['name']:20s} +{m['increase_rate']:5.1f}%  {bar}")

    print(f"\n【平松建築 事業影響】")
    print(f"  契約済み未着工損失: ▲{format_currency(hiramatsu['backlog_loss'])}")
    print(f"  粗利率:  {hiramatsu['normal_gross_margin']}% → {hiramatsu['shocked_gross_margin']}%")
    print(f"  需要減:  {hiramatsu['demand_change_houses']}棟/年")
    print(f"  年間利益影響: ▲{format_currency(hiramatsu['annual_profit_impact'])}")

    print(f"\n【住まい手 家計影響】")
    print(f"  月額負担増: +{format_currency(homeowner['total_monthly_household_impact'])}/月")
    print(f"  新築価格:   +{format_currency(homeowner['new_home_increase'])}（+{homeowner['new_home_increase_rate']}%）")

    print(f"\n【緩和策】")
    for i, s in enumerate(strategies, 1):
        print(f"  {i}. {s['name']:30s} → ▲{format_currency(s['reduction_amount'])}軽減  [{s['timeline']}]")

    print("\n" + "=" * 70)


# ============================================================
# メイン
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="ホルムズ海峡封鎖 住宅業界影響シミュレーター（平松建築版）"
    )
    parser.add_argument("--scenario", choices=list(SCENARIOS.keys()), default="partial",
                        help="封鎖シナリオ (default: partial)")
    parser.add_argument("--duration", type=int, default=90,
                        help="封鎖期間（日数, default: 90）")
    parser.add_argument("--save-to-vault", action="store_true",
                        help="レポートをObsidian Vaultに保存")
    parser.add_argument("--output", type=str, default=None,
                        help="出力ファイルパス（指定時はそこに保存）")
    parser.add_argument("--youtube", action="store_true",
                        help="YouTube台本セクションを強調表示")
    parser.add_argument("--month", type=str, default=None,
                        help="レポート対象月 (YYYY-MM)")
    parser.add_argument("--all-scenarios", action="store_true",
                        help="全シナリオを比較実行")
    parser.add_argument("--json", action="store_true",
                        help="JSON形式で出力")

    args = parser.parse_args()

    report_date = datetime.now().strftime("%Y-%m-%d")

    if args.all_scenarios:
        print("\n全シナリオ比較:")
        print(f"{'シナリオ':20s} {'建材コスト増/棟':>14s} {'年間利益影響':>14s} {'住まい手月額増':>14s}")
        print("-" * 66)
        for sk in SCENARIOS:
            prices = calc_oil_price(sk, args.duration)
            mats, tb, ts = calc_material_impact(sk, args.duration)
            hi = calc_hiramatsu_impact(sk, args.duration, mats, tb, ts)
            ho = calc_homeowner_impact(sk, args.duration)
            print(f"{SCENARIOS[sk]['label']:20s} +{format_currency(hi['cost_increase_per_house']):>12s} ▲{format_currency(hi['annual_profit_impact']):>12s} +{format_currency(ho['total_monthly_household_impact']):>12s}")
        print()
        return

    # 単一シナリオ実行
    prices = calc_oil_price(args.scenario, args.duration)
    materials, total_base, total_shocked = calc_material_impact(args.scenario, args.duration)
    hiramatsu = calc_hiramatsu_impact(args.scenario, args.duration, materials, total_base, total_shocked)
    homeowner = calc_homeowner_impact(args.scenario, args.duration)
    strategies = calc_mitigation_strategies(args.scenario, hiramatsu)

    if args.json:
        output = {
            "scenario": SCENARIOS[args.scenario],
            "duration_days": args.duration,
            "materials": materials,
            "hiramatsu_impact": hiramatsu,
            "homeowner_impact": homeowner,
            "strategies": strategies,
            "generated": report_date,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return

    # コンソール出力
    print_summary(args.scenario, args.duration, materials, total_base, total_shocked,
                  hiramatsu, homeowner, strategies)

    # Markdownレポート生成
    report = generate_report(
        args.scenario, args.duration, prices, materials, total_base, total_shocked,
        hiramatsu, homeowner, strategies, report_date
    )

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        print(f"\nレポート保存: {out_path}")

    elif args.save_to_vault:
        folder = VAULT_ROOT / "01_Projects"
        folder.mkdir(parents=True, exist_ok=True)
        filename = f"{datetime.now().strftime('%Y%m%d')}_ホルムズ海峡_住宅影響_{args.scenario}.md"
        out_path = folder / filename
        out_path.write_text(report, encoding="utf-8")
        print(f"\nVaultに保存: {out_path}")

    else:
        print("\n※ --save-to-vault または --output <path> でレポートを保存できます")


if __name__ == "__main__":
    main()
