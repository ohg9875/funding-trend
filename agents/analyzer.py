"""
Analyzer Agent — 펀딩 트렌드 MVP
전처리된 데이터를 분석해 굿즈 카테고리별 트렌드 패턴 도출

TREND_SCORE 공식:
  과거 데이터 있음: 성공률×0.35 + 달성률×0.25 + 후원자증가추세×0.20 + 포화도역산×0.20
  과거 데이터 없음: 성공률×0.42 + 달성률×0.30 + 포화도역산×0.28

출력: data/processed/trend_analysis_YYYYMMDD.json
"""

import json
import logging
import os
from datetime import datetime
from glob import glob

import pandas as pd

logger = logging.getLogger(__name__)

MIN_SAMPLE = 3             # 분석 최소 샘플 수
SATURATION_THRESHOLD = 30  # 포화도 경고 기준 (프로젝트 수)


# ── TREND_SCORE ───────────────────────────────────────────────────────
# cap 기준: 달성률 500%, 후원자 1000명
# 포화도역산: 해당 카테고리 프로젝트 수 많을수록 낮음 (경쟁 과열)

def _calc_trend_score(row: pd.Series, has_history: bool = False) -> float:
    """
    TREND_SCORE 계산 (0~100)

    has_history=True:
      성공률×0.35 + 달성률×0.25 + 후원자증가추세×0.20 + 포화도역산×0.20
    has_history=False:
      성공률×0.42 + 달성률×0.30 + 포화도역산×0.28
    """
    success_score = 100.0 if row.get("achieved_rate", 0) >= 100 else 0.0
    rate_score    = min(row.get("achieved_rate", 0) / 500.0, 1.0) * 100
    saturation_inv = row.get("saturation_inv", 50.0)  # 0~100
    trend_score_val = row.get("backer_trend", 50.0)   # 0~100 (히스토리 있을 때만 의미 있음)

    if has_history:
        score = (
            success_score   * 0.35
            + rate_score    * 0.25
            + trend_score_val * 0.20
            + saturation_inv  * 0.20
        )
    else:
        score = (
            success_score   * 0.42
            + rate_score    * 0.30
            + saturation_inv  * 0.28
        )

    return round(score, 2)


def _calc_saturation_inv(count: int, threshold: int = SATURATION_THRESHOLD) -> float:
    """카테고리 내 프로젝트 수 → 포화도역산 점수 (0~100). 많을수록 낮음."""
    return max(0.0, round(100.0 - (count / threshold * 100), 1))


def _success_rate(df: pd.DataFrame) -> float:
    if df.empty:
        return 0.0
    return round((df["achieved_rate"] >= 100).sum() / len(df) * 100, 1)


def _safe_stats(series: pd.Series) -> dict:
    if series.empty:
        return {"mean": 0, "median": 0, "count": 0}
    return {
        "mean": round(float(series.mean()), 1),
        "median": round(float(series.median()), 1),
        "count": int(series.count()),
    }


def analyze(df: pd.DataFrame, has_history: bool = False) -> dict:
    if df.empty:
        return {
            "by_goods_category": {},
            "by_platform": {},
            "top_projects": [],
            "early_success_projects": [],
            "saturation_warnings": [],
            "summary": {
                "total_projects": 0,
                "success_rate_pct": 0,
                "avg_achieved_rate": 0,
                "avg_backers": 0,
            },
        }

    df = df.copy()

    # 카테고리별 포화도역산 사전 계산
    cat_counts = df["goods_category"].value_counts().to_dict()
    df["saturation_inv"] = df["goods_category"].map(
        lambda c: _calc_saturation_inv(cat_counts.get(c, 0))
    )
    df["backer_trend"] = 50.0  # 히스토리 없으면 중립값

    df["trend_score"] = df.apply(
        lambda r: _calc_trend_score(r, has_history=has_history), axis=1
    )

    # ── 1. 굿즈 카테고리별 분석 ──
    by_goods_category = {}
    for cat, group in df.groupby("goods_category"):
        if len(group) < MIN_SAMPLE:
            logger.debug(f"샘플 부족 제외: {cat} ({len(group)}건)")
            continue
        by_goods_category[cat] = {
            "count": len(group),
            "success_rate_pct": _success_rate(group),
            "achieved_rate": _safe_stats(group["achieved_rate"]),
            "backers": _safe_stats(group["backers"]),
            "raised_amount": _safe_stats(group["raised_amount"]),
            "avg_trend_score": round(float(group["trend_score"].mean()), 2),
            "saturation_inv": round(float(group["saturation_inv"].iloc[0]), 1),
            "early_success_count": int(group["early_success"].sum()),
        }

    # ── 2. 플랫폼별 분석 ──
    by_platform = {}
    for platform, group in df.groupby("platform"):
        if len(group) < MIN_SAMPLE:
            continue
        by_platform[platform] = {
            "count": len(group),
            "success_rate_pct": _success_rate(group),
            "achieved_rate": _safe_stats(group["achieved_rate"]),
            "backers": _safe_stats(group["backers"]),
        }

    # ── 3. TOP 프로젝트 (trend_score 기준) ──
    top_cols = [
        "title", "creator", "link", "platform", "goods_category",
        "achieved_rate", "backers", "raised_amount", "early_success", "trend_score",
    ]
    existing = [c for c in top_cols if c in df.columns]
    top = df.nlargest(10, "trend_score")[existing].to_dict(orient="records")

    # ── 4. 조기 달성 프로젝트 ──
    early_df = df[df["early_success"] == True]
    early_cols = ["title", "achieved_rate", "backers", "goods_category", "platform"]
    early_existing = [c for c in early_cols if c in df.columns]
    early_list = early_df.nlargest(5, "achieved_rate")[early_existing].to_dict(orient="records")

    # ── 5. 포화도 경고 ──
    saturation_warnings = [
        {"goods_category": cat, "count": cnt}
        for cat, cnt in cat_counts.items()
        if cnt >= SATURATION_THRESHOLD
    ]

    # ── 6. 전체 요약 ──
    summary = {
        "total_projects": len(df),
        "success_rate_pct": _success_rate(df),
        "avg_achieved_rate": round(float(df["achieved_rate"].mean()), 1),
        "avg_backers": round(float(df["backers"].mean()), 1),
        "early_success_count": int(df["early_success"].sum()),
        "has_history": has_history,
        "goods_category_counts": cat_counts,
        "platform_counts": df["platform"].value_counts().to_dict(),
        "analyzed_at": datetime.now().isoformat(),
    }

    return {
        "by_goods_category": by_goods_category,
        "by_platform": by_platform,
        "top_projects": top,
        "early_success_projects": early_list,
        "saturation_warnings": saturation_warnings,
        "summary": summary,
    }


def compare_with_previous(current: dict, previous: dict) -> dict:
    """
    이번 주 vs 지난 주 카테고리별 TREND_SCORE 변화 계산

    반환:
      {
        "아크릴": {"current": 85.5, "previous": 82.3, "delta": +3.2, "direction": "up"},
        "키링":   {"current": 65.0, "previous": 66.4, "delta": -1.4, "direction": "down"},
        ...
      }
    """
    curr_cats = current.get("by_goods_category", {})
    prev_cats = previous.get("by_goods_category", {})

    comparison = {}
    all_cats = set(curr_cats) | set(prev_cats)

    for cat in all_cats:
        curr_score = curr_cats.get(cat, {}).get("avg_trend_score", 0.0)
        prev_score = prev_cats.get(cat, {}).get("avg_trend_score", 0.0)
        delta = round(curr_score - prev_score, 2)
        comparison[cat] = {
            "current": curr_score,
            "previous": prev_score,
            "delta": delta,
            "direction": "up" if delta > 0 else ("down" if delta < 0 else "flat"),
            "new_this_week": cat not in prev_cats,
        }

    return dict(sorted(comparison.items(), key=lambda x: abs(x[1]["delta"]), reverse=True))


def run_analyzer(
    processed_dir: str = "data/processed",
    output_dir: str = "data/processed",
) -> dict:
    """분석 실행"""
    pattern = os.path.join(processed_dir, "unified_*.json")
    files = sorted(glob(pattern), reverse=True)
    if not files:
        raise ValueError("전처리 파일 없음 — 전처리를 먼저 실행해주세요")

    with open(files[0], encoding="utf-8") as f:
        data = json.load(f)

    if not data:
        raise ValueError("전처리 데이터가 비어 있습니다")

    df = pd.DataFrame(data)
    logger.info(f"분석 대상: {len(df)}건")

    # 과거 분석 파일 있으면 has_history=True
    history_pattern = os.path.join(processed_dir, "trend_analysis_*.json")
    has_history = len(glob(history_pattern)) > 0
    logger.info(f"과거 데이터 유무: {has_history}")

    result = analyze(df, has_history=has_history)

    # ── 이전 주 대비 비교 ─────────────────────────────────────────────
    history_files = sorted(glob(history_pattern), reverse=True)
    if history_files:
        with open(history_files[0], encoding="utf-8") as f:
            previous = json.load(f)
        comparison = compare_with_previous(result, previous)
        result["week_over_week"] = comparison

        # 상위 변동 로그
        top_changes = list(comparison.items())[:5]
        change_log = ", ".join(
            f"{cat} {v['delta']:+.1f}" for cat, v in top_changes if v["delta"] != 0
        )
        if change_log:
            logger.info(f"주간 변동 (top5): {change_log}")
    else:
        result["week_over_week"] = {}

    os.makedirs(output_dir, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d")
    output_path = os.path.join(output_dir, f"trend_analysis_{date_str}.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    logger.info(f"분석 완료 → {output_path}")

    if result.get("saturation_warnings"):
        for w in result["saturation_warnings"]:
            logger.warning(
                f"포화도 경고: {w['goods_category']} — {w['count']}건 "
                f"(임계값 {SATURATION_THRESHOLD}건 초과)"
            )

    return result


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
    )
    from dotenv import load_dotenv
    load_dotenv()
    result = run_analyzer()
    s = result["summary"]
    print(
        f"총 {s['total_projects']}건 | 성공률 {s['success_rate_pct']}%"
        f" | 평균달성률 {s['avg_achieved_rate']}%"
    )
    print(f"굿즈 카테고리별: {list(result['by_goods_category'].keys())}")
