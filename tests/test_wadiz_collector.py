"""Wadiz Collector 단위 테스트"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.wadiz_collector import _parse_rate, _parse_int, _parse_project, CATEGORY_CODES


def test_parse_rate_float():
    assert _parse_rate(1.5) == 1.5


def test_parse_rate_string():
    assert _parse_rate("250") == 250.0


def test_parse_rate_invalid():
    assert _parse_rate("없음") == 0.0


def test_parse_int_int():
    assert _parse_int(100) == 100


def test_parse_int_string():
    assert _parse_int("2,500명") == 2500


def test_parse_int_invalid():
    assert _parse_int(None) == 0


def test_parse_project_valid():
    item = {
        "title": "캐릭터 굿즈 세트",
        "campaignId": "12345",
        "achievementRate": 450,
        "participationCnt": 800,
        "totalBackedAmount": 9000000,
        "remainingDay": 10,
        "corpName": "굿즈스튜디오",
        "categoryName": "캐릭터·굿즈",
    }
    proj = _parse_project(item)
    assert proj is not None
    assert proj["title"] == "캐릭터 굿즈 세트"
    assert proj["achieved_rate"] == 450.0
    assert proj["backers"] == 800
    assert proj["early_success"] is True  # remaining > 0 && rate >= 100
    assert proj["platform"] == "wadiz"
    assert proj["campaign_id"] == "12345"


def test_parse_project_no_title():
    assert _parse_project({"campaignId": "999"}) is None


def test_parse_project_cap_rate():
    item = {"title": "초과달성", "campaignId": "1", "achievementRate": 99999}
    proj = _parse_project(item)
    assert proj["achieved_rate"] == 9999.0


def test_parse_project_not_early_success_if_ended():
    item = {
        "title": "마감됨",
        "campaignId": "2",
        "achievementRate": 500,
        "remainingDay": 0,  # 마감
    }
    proj = _parse_project(item)
    assert proj["early_success"] is False


def test_parse_project_creator_fallback():
    """corpName 없으면 nickName 사용"""
    item = {
        "title": "개인 크리에이터",
        "campaignId": "3",
        "nickName": "닉네임123",
    }
    proj = _parse_project(item)
    assert proj["creator"] == "닉네임123"


def test_category_codes_include_goods_categories():
    codes = [c[0] for c in CATEGORY_CODES]
    assert "A0120" in codes  # 캐릭터·굿즈
    assert "A0100" in codes  # 라이프스타일
    assert "A0150" in codes  # 패션·뷰티
    assert "A0130" in codes  # 테크·가전
    assert "A0200" in codes  # 푸드


if __name__ == "__main__":
    test_parse_rate_float()
    test_parse_rate_string()
    test_parse_rate_invalid()
    test_parse_int_int()
    test_parse_int_string()
    test_parse_int_invalid()
    test_parse_project_valid()
    test_parse_project_no_title()
    test_parse_project_cap_rate()
    test_parse_project_not_early_success_if_ended()
    test_parse_project_creator_fallback()
    test_category_codes_include_goods_categories()
    print("모든 테스트 통과")
