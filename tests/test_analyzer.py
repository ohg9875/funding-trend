"""Analyzer 단위 테스트 — TREND_SCORE 조건 분기 포함"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from agents.analyzer import (
    _calc_trend_score, _calc_saturation_inv,
    _success_rate, _safe_stats, analyze, compare_with_previous,
    SATURATION_THRESHOLD,
)


def _make_df(rows):
    return pd.DataFrame(rows)


def _base_row(**kwargs):
    defaults = {
        "achieved_rate": 200.0,
        "backers": 300,
        "early_success": False,
        "saturation_inv": 50.0,
        "backer_trend": 50.0,
    }
    defaults.update(kwargs)
    return pd.Series(defaults)


# ── TREND_SCORE 테스트 ─────────────────────────────────────────────────

def test_trend_score_range():
    row = _base_row(achieved_rate=500, backers=1000, early_success=True)
    for has_history in [True, False]:
        score = _calc_trend_score(row, has_history=has_history)
        assert 0 <= score <= 100, f"범위 초과: {score}"


def test_trend_score_zero():
    row = _base_row(achieved_rate=0, backers=0, early_success=False, saturation_inv=0.0, backer_trend=0.0)
    assert _calc_trend_score(row, has_history=False) == 0.0
    assert _calc_trend_score(row, has_history=True) == 0.0


def test_trend_score_no_history_weights():
    """has_history=False: 성공률 가중치가 더 높아야 함"""
    # 달성률 100% → 성공(100점) 기여가 0.42(no_history) vs 0.35(history)
    row_success = _base_row(achieved_rate=100, saturation_inv=0.0, backer_trend=0.0)
    score_no_hist = _calc_trend_score(row_success, has_history=False)
    score_hist = _calc_trend_score(row_success, has_history=True)
    assert score_no_hist > score_hist, "히스토리 없을 때 성공률 가중치 더 높아야 함"


def test_trend_score_history_backer_trend_matters():
    """has_history=True: backer_trend가 점수에 영향을 줘야 함"""
    row_low_trend = _base_row(achieved_rate=100, backer_trend=0.0, saturation_inv=50.0)
    row_high_trend = _base_row(achieved_rate=100, backer_trend=100.0, saturation_inv=50.0)
    score_low = _calc_trend_score(row_low_trend, has_history=True)
    score_high = _calc_trend_score(row_high_trend, has_history=True)
    assert score_high > score_low


# ── 포화도역산 테스트 ──────────────────────────────────────────────────

def test_saturation_inv_below_threshold():
    score = _calc_saturation_inv(0)
    assert score == 100.0


def test_saturation_inv_at_threshold():
    score = _calc_saturation_inv(SATURATION_THRESHOLD)
    assert score == 0.0


def test_saturation_inv_clamped():
    score = _calc_saturation_inv(SATURATION_THRESHOLD * 2)
    assert score == 0.0


# ── 성공률 테스트 ──────────────────────────────────────────────────────

def test_success_rate():
    df = _make_df([
        {"achieved_rate": 100},
        {"achieved_rate": 50},
        {"achieved_rate": 200},
    ])
    assert abs(_success_rate(df) - 66.7) < 0.1


def test_success_rate_empty():
    assert _success_rate(_make_df([])) == 0.0


# ── safe_stats 테스트 ──────────────────────────────────────────────────

def test_safe_stats_normal():
    series = pd.Series([100.0, 200.0, 300.0])
    result = _safe_stats(series)
    assert result["mean"] == 200.0
    assert result["count"] == 3


def test_safe_stats_empty():
    result = _safe_stats(pd.Series([], dtype=float))
    assert result["count"] == 0
    assert result["mean"] == 0


# ── analyze() 통합 테스트 ─────────────────────────────────────────────

SAMPLE_ROWS = [
    {
        "title": f"프로젝트{i}",
        "creator": f"크리에이터{i}",
        "platform": "tumblbug" if i % 2 == 0 else "wadiz",
        "goods_category": "키링",
        "achieved_rate": 150.0 + i * 20,
        "backers": 100 + i * 30,
        "raised_amount": 500000,
        "early_success": i % 3 == 0,
        "remaining_day": -1,
    }
    for i in range(5)
]


def test_analyze_single_category():
    df = _make_df(SAMPLE_ROWS)
    result = analyze(df, has_history=False)
    assert "by_goods_category" in result
    assert "키링" in result["by_goods_category"]
    assert result["summary"]["total_projects"] == 5


def test_analyze_has_history_flag():
    df = _make_df(SAMPLE_ROWS)
    r_no_hist = analyze(df, has_history=False)
    r_hist = analyze(df, has_history=True)
    assert r_no_hist["summary"]["has_history"] is False
    assert r_hist["summary"]["has_history"] is True


def test_analyze_saturation_warning():
    """SATURATION_THRESHOLD 이상이면 경고 발생"""
    rows = [
        {"title": f"p{i}", "creator": "", "platform": "wadiz",
         "goods_category": "키링", "achieved_rate": 100.0,
         "backers": 50, "raised_amount": 100000, "early_success": False,
         "remaining_day": -1}
        for i in range(SATURATION_THRESHOLD)
    ]
    df = _make_df(rows)
    result = analyze(df)
    warnings = [w["goods_category"] for w in result["saturation_warnings"]]
    assert "키링" in warnings


def test_analyze_empty_no_crash():
    df = _make_df([])
    result = analyze(df)
    assert result["summary"]["total_projects"] == 0
    assert result["by_goods_category"] == {}


def test_analyze_top_projects_count():
    df = _make_df(SAMPLE_ROWS)
    result = analyze(df)
    assert len(result["top_projects"]) <= 10


# ── compare_with_previous() 테스트 ────────────────────────────────────────

def _make_analysis(cat_scores: dict) -> dict:
    """테스트용 최소 분석 결과 생성"""
    return {
        "by_goods_category": {
            cat: {"avg_trend_score": score}
            for cat, score in cat_scores.items()
        }
    }


def test_compare_up():
    current = _make_analysis({"아크릴": 85.5, "키링": 65.0})
    previous = _make_analysis({"아크릴": 82.3, "키링": 66.4})
    result = compare_with_previous(current, previous)
    assert result["아크릴"]["direction"] == "up"
    assert result["아크릴"]["delta"] == round(85.5 - 82.3, 2)


def test_compare_down():
    current = _make_analysis({"키링": 65.0})
    previous = _make_analysis({"키링": 66.4})
    result = compare_with_previous(current, previous)
    assert result["키링"]["direction"] == "down"
    assert result["키링"]["delta"] < 0


def test_compare_flat():
    current = _make_analysis({"파우치": 70.0})
    previous = _make_analysis({"파우치": 70.0})
    result = compare_with_previous(current, previous)
    assert result["파우치"]["direction"] == "flat"
    assert result["파우치"]["delta"] == 0


def test_compare_new_this_week():
    """이번 주 신규 카테고리는 new_this_week=True"""
    current = _make_analysis({"아크릴": 85.0, "신규카테고리": 50.0})
    previous = _make_analysis({"아크릴": 80.0})
    result = compare_with_previous(current, previous)
    assert result["신규카테고리"]["new_this_week"] is True
    assert result["아크릴"]["new_this_week"] is False


def test_compare_missing_category_in_current():
    """지난 주엔 있었지만 이번 주엔 없는 카테고리 → current=0"""
    current = _make_analysis({"아크릴": 85.0})
    previous = _make_analysis({"아크릴": 80.0, "사라진카테고리": 40.0})
    result = compare_with_previous(current, previous)
    assert "사라진카테고리" in result
    assert result["사라진카테고리"]["current"] == 0.0


def test_compare_sorted_by_abs_delta():
    """절댓값 변화량 큰 순서로 정렬"""
    current = _make_analysis({"A": 90.0, "B": 50.0, "C": 70.0})
    previous = _make_analysis({"A": 80.0, "B": 49.0, "C": 40.0})
    result = compare_with_previous(current, previous)
    deltas = [abs(v["delta"]) for v in result.values()]
    assert deltas == sorted(deltas, reverse=True)


if __name__ == "__main__":
    test_trend_score_range()
    test_trend_score_zero()
    test_trend_score_no_history_weights()
    test_trend_score_history_backer_trend_matters()
    test_saturation_inv_below_threshold()
    test_saturation_inv_at_threshold()
    test_saturation_inv_clamped()
    test_success_rate()
    test_success_rate_empty()
    test_safe_stats_normal()
    test_safe_stats_empty()
    test_analyze_single_category()
    test_analyze_has_history_flag()
    test_analyze_saturation_warning()
    test_analyze_empty_no_crash()
    test_analyze_top_projects_count()
    test_compare_up()
    test_compare_down()
    test_compare_flat()
    test_compare_new_this_week()
    test_compare_missing_category_in_current()
    test_compare_sorted_by_abs_delta()
    print("모든 테스트 통과")
