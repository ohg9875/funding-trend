"""Launch Advisor 단위 테스트 — JSON 파싱 실패, 빈 컨셉, HTML 길이 검증, mock patch"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch, MagicMock
from agents.launch_advisor import (
    _parse_json_response, _select_top_concept,
    HTML_MIN_LENGTH,
)


# ── _parse_json_response ──────────────────────────────────────────────

def test_parse_json_clean_array():
    text = '[{"rank": 1, "concept_name": "키링 세트"}]'
    result = _parse_json_response(text)
    assert isinstance(result, list)
    assert result[0]["rank"] == 1


def test_parse_json_with_codefence():
    text = '```json\n[{"a": 1}]\n```'
    result = _parse_json_response(text)
    assert result == [{"a": 1}]


def test_parse_json_with_preamble():
    text = "다음은 컨셉입니다:\n\n[{\"rank\": 1}]"
    result = _parse_json_response(text)
    assert isinstance(result, list)


def test_parse_json_object():
    text = '{"instagram_caption": "테스트 캡션"}'
    result = _parse_json_response(text)
    assert isinstance(result, dict)
    assert "instagram_caption" in result


def test_parse_json_invalid_returns_none():
    result = _parse_json_response("이건 JSON이 아닙니다 { 완전히 깨진 내용")
    assert result is None


def test_parse_json_empty_returns_none():
    assert _parse_json_response("") is None
    assert _parse_json_response(None) is None


# ── _select_top_concept ───────────────────────────────────────────────

def test_select_top_concept_by_success_rate():
    concepts = [
        {"concept_name": "A", "expected_success_rate": 60},
        {"concept_name": "B", "expected_success_rate": 85},
        {"concept_name": "C", "expected_success_rate": 72},
    ]
    top = _select_top_concept(concepts)
    assert top["concept_name"] == "B"


def test_select_top_concept_empty_list():
    result = _select_top_concept([])
    assert result == {}


def test_select_top_concept_missing_rate():
    """expected_success_rate 없는 항목 처리 (기본값 0)"""
    concepts = [
        {"concept_name": "X"},
        {"concept_name": "Y", "expected_success_rate": 50},
    ]
    top = _select_top_concept(concepts)
    assert top["concept_name"] == "Y"


# ── run_launch_advisor mock 테스트 ────────────────────────────────────

MOCK_CONCEPTS = [
    {
        "rank": 1,
        "concept_name": "감성 아크릴 키링",
        "goods_category": "키링",
        "target_audience": "20대 여성",
        "product_description": "귀여운 캐릭터 키링",
        "price_range": "15,000~20,000원",
        "funding_goal": "300만원",
        "expected_success_rate": 78,
        "differentiation": "한정판 컬러웨이",
        "trend_basis": "키링 TREND_SCORE 최상위",
    }
]

MOCK_HTML = "<!DOCTYPE html>" + "x" * HTML_MIN_LENGTH
MOCK_SNS = '{"instagram_caption": "인스타 테스트", "twitter_post": "트위터 테스트"}'

MOCK_ANALYSIS = {
    "by_goods_category": {"키링": {"avg_trend_score": 72, "success_rate_pct": 70, "count": 10}},
    "top_projects": [],
    "saturation_warnings": [],
    "summary": {"total_projects": 50, "success_rate_pct": 68, "avg_achieved_rate": 210, "avg_backers": 180},
}


def test_run_launch_advisor_success(tmp_path):
    """정상 흐름: 컨셉 생성 → HTML + SNS 병렬 생성 → 파일 저장"""
    import json

    # 분석 파일 픽스처
    processed_dir = str(tmp_path / "processed")
    os.makedirs(processed_dir)
    from datetime import datetime
    date_str = datetime.now().strftime("%Y%m%d")
    analysis_path = os.path.join(processed_dir, f"trend_analysis_{date_str}.json")
    with open(analysis_path, "w", encoding="utf-8") as f:
        json.dump(MOCK_ANALYSIS, f)

    output_dir = str(tmp_path / "reports")
    pages_dir = str(tmp_path / "pages")

    call_returns = [
        json.dumps(MOCK_CONCEPTS),  # Step1: concepts
        MOCK_HTML,                   # Step2: HTML
        MOCK_SNS,                    # Step3: SNS
    ]
    call_iter = iter(call_returns)

    with patch("agents.launch_advisor.call_claude", side_effect=lambda *a, **kw: next(call_iter)):
        from agents.launch_advisor import run_launch_advisor
        result = run_launch_advisor(
            processed_dir=processed_dir,
            output_dir=output_dir,
            pages_dir=pages_dir,
        )

    assert result is not None
    assert os.path.exists(result)  # concepts JSON 저장됨
    assert os.path.exists(os.path.join(pages_dir, f"funding_page_{date_str}.html"))
    assert os.path.exists(os.path.join(pages_dir, f"sns_copy_{date_str}.json"))


def test_run_launch_advisor_step1_fail(tmp_path):
    """Step1 실패 시 None 반환"""
    import json

    processed_dir = str(tmp_path / "processed")
    os.makedirs(processed_dir)
    from datetime import datetime
    date_str = datetime.now().strftime("%Y%m%d")
    with open(os.path.join(processed_dir, f"trend_analysis_{date_str}.json"), "w") as f:
        json.dump(MOCK_ANALYSIS, f)

    with patch("agents.launch_advisor.call_claude", return_value=None):
        from agents.launch_advisor import run_launch_advisor
        result = run_launch_advisor(
            processed_dir=processed_dir,
            output_dir=str(tmp_path / "reports"),
            pages_dir=str(tmp_path / "pages"),
        )

    assert result is None


def test_run_launch_advisor_html_short_retried(tmp_path):
    """HTML 길이 미달 시 재시도하고 긴 버전 사용"""
    import json

    processed_dir = str(tmp_path / "processed")
    os.makedirs(processed_dir)
    from datetime import datetime
    date_str = datetime.now().strftime("%Y%m%d")
    with open(os.path.join(processed_dir, f"trend_analysis_{date_str}.json"), "w") as f:
        json.dump(MOCK_ANALYSIS, f)

    short_html = "<!DOCTYPE html><html><body>short</body></html>"
    long_html = "<!DOCTYPE html>" + "x" * HTML_MIN_LENGTH

    call_seq = [
        json.dumps(MOCK_CONCEPTS),  # Step1
        short_html,                  # Step2 (짧음 → 재시도 트리거)
        long_html,                   # Step2 재시도
        MOCK_SNS,                    # Step3
    ]
    call_iter = iter(call_seq)

    with patch("agents.launch_advisor.call_claude", side_effect=lambda *a, **kw: next(call_iter)):
        from agents.launch_advisor import run_launch_advisor
        run_launch_advisor(
            processed_dir=processed_dir,
            output_dir=str(tmp_path / "reports"),
            pages_dir=str(tmp_path / "pages"),
        )

    html_path = os.path.join(str(tmp_path / "pages"), f"funding_page_{date_str}.html")
    if os.path.exists(html_path):
        with open(html_path, encoding="utf-8") as f:
            content = f.read()
        assert len(content) >= HTML_MIN_LENGTH


if __name__ == "__main__":
    test_parse_json_clean_array()
    test_parse_json_with_codefence()
    test_parse_json_with_preamble()
    test_parse_json_object()
    test_parse_json_invalid_returns_none()
    test_parse_json_empty_returns_none()
    test_select_top_concept_by_success_rate()
    test_select_top_concept_empty_list()
    test_select_top_concept_missing_rate()
    print("단위 테스트 통과 (통합 테스트는 pytest로 실행)")
