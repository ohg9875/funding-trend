"""Tumblbug Collector 단위 테스트"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.tumblbug_collector import _parse_rate, _parse_int, _parse_project_from_api, CATEGORIES


def test_parse_rate_float():
    assert _parse_rate(3.14) == 3.14


def test_parse_rate_string_with_percent():
    assert _parse_rate("250%") == 250.0


def test_parse_rate_string_with_comma():
    assert _parse_rate("1,234.5") == 1234.5


def test_parse_rate_invalid():
    assert _parse_rate("N/A") == 0.0


def test_parse_int_int():
    assert _parse_int(42) == 42


def test_parse_int_string():
    assert _parse_int("1,234명") == 1234


def test_parse_int_invalid():
    assert _parse_int(None) == 0


def test_parse_project_from_api_valid():
    item = {
        "title": "귀여운 키링",
        "permalink": "cute-keyring",
        "percentage": "350",
        "pledgedCount": 500,
        "amount": 5000000,
        "endDate": "2024-12-31",
        "startDate": "2024-11-01",
        "creatorName": "홍길동",
        "categoryName": "캐릭터·굿즈",
    }
    proj = _parse_project_from_api(item)
    assert proj is not None
    assert proj["title"] == "귀여운 키링"
    assert proj["achieved_rate"] == 350.0
    assert proj["backers"] == 500
    assert proj["platform"] == "tumblbug"
    assert proj["launch_month"] == 11
    assert proj["launch_weekday"] == "Friday"


def test_parse_project_from_api_no_title():
    assert _parse_project_from_api({"title": "", "permalink": "test"}) is None


def test_parse_project_from_api_cap_rate():
    item = {"title": "테스트", "permalink": "test", "percentage": 99999}
    proj = _parse_project_from_api(item)
    assert proj["achieved_rate"] == 9999.0


def test_parse_project_from_api_missing_start_date():
    item = {"title": "날짜없음", "permalink": "no-date"}
    proj = _parse_project_from_api(item)
    assert proj is not None
    assert proj["launch_month"] is None
    assert proj["launch_weekday"] is None


def test_default_categories_include_food_and_tech():
    assert "food" in CATEGORIES
    assert "tech" in CATEGORIES
    assert "character-and-goods" in CATEGORIES
    assert "design-stationery" in CATEGORIES


if __name__ == "__main__":
    test_parse_rate_float()
    test_parse_rate_string_with_percent()
    test_parse_rate_string_with_comma()
    test_parse_rate_invalid()
    test_parse_int_int()
    test_parse_int_string()
    test_parse_int_invalid()
    test_parse_project_from_api_valid()
    test_parse_project_from_api_no_title()
    test_parse_project_from_api_cap_rate()
    test_parse_project_from_api_missing_start_date()
    test_default_categories_include_food_and_tech()
    print("모든 테스트 통과")
