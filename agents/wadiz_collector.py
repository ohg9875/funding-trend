"""
Wadiz Collector Agent — 펀딩 트렌드 MVP
와디즈 굿즈/라이프스타일 카테고리 수집 (Playwright + 내부 JSON API)
HTML 스크래핑 X — service.wadiz.kr 내부 API 직접 호출

카테고리 코드:
  A0120: 캐릭터·굿즈
  A0100: 라이프스타일
  A0150: 패션·뷰티
  A0130: 테크·가전
  A0200: 푸드

출력: data/raw/wadiz_YYYYMMDD.json
"""

import json
import logging
import os
import random
import time
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin

import yaml

logger = logging.getLogger(__name__)

BASE_URL = "https://www.wadiz.kr"
API_URL = "https://service.wadiz.kr/api/search/v2/funding"

# 카테고리 코드: (api_code, web_url_code)
# web_url_code = 와디즈 카테고리 페이지 숫자 (세션 초기화용)
CATEGORY_CODES = [
    ("A0120", "310"),  # 캐릭터·굿즈
    ("A0100", "300"),  # 라이프스타일
    ("A0150", "320"),  # 패션·뷰티
    ("A0130", "330"),  # 테크·가전
    ("A0200", "340"),  # 푸드
]
PAGE_SIZE = 48


def _parse_rate(text) -> float:
    try:
        if isinstance(text, (int, float)):
            return float(text)
        cleaned = "".join(c for c in str(text) if c.isdigit() or c == ".")
        return float(cleaned) if cleaned else 0.0
    except (ValueError, TypeError):
        return 0.0


def _parse_int(text) -> int:
    try:
        if isinstance(text, int):
            return text
        return int("".join(filter(str.isdigit, str(text))))
    except (ValueError, TypeError):
        return 0


def _parse_project(item: dict) -> Optional[dict]:
    """API 응답 항목 → 프로젝트 dict"""
    try:
        title = item.get("title", "").strip()
        if not title:
            return None

        campaign_id = item.get("campaignId", "")
        link = urljoin(BASE_URL, f"/web/campaign/detail/{campaign_id}") if campaign_id else ""

        achieved_rate = _parse_rate(item.get("achievementRate", 0))
        backers = _parse_int(item.get("participationCnt", 0))
        raised_amount = _parse_int(item.get("totalBackedAmount", 0))
        remaining_day = item.get("remainingDay", -1)

        try:
            remaining = int(remaining_day) if remaining_day is not None else -1
        except (ValueError, TypeError):
            remaining = -1
        early_success = (remaining > 0) and (achieved_rate >= 100.0)

        creator = item.get("corpName") or item.get("nickName") or ""
        category_name = item.get("categoryName", "")

        return {
            "title": title,
            "creator": creator,
            "link": link,
            "campaign_id": str(campaign_id),
            "platform": "wadiz",
            "achieved_rate": min(float(achieved_rate), 9999.0),
            "backers": backers,
            "raised_amount": raised_amount,
            "goal_amount": 0,           # 목록 API 미제공
            "early_success": early_success,
            "remaining_day": remaining,
            "rewards": [],
            "reward_count": 0,
            "min_reward_price": 0,
            "max_reward_price": 0,
            "tags": [category_name] if category_name else [],
            "goods_category": "",       # preprocessor에서 분류
            "collected_at": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.debug(f"항목 파싱 오류: {e}")
        return None


def _collect_category(
    page,
    api_code: str,
    web_code: str,
    max_pages: int,
    delay_min: float,
    delay_max: float,
) -> list:
    """단일 카테고리 수집"""
    projects = []
    seen_ids = set()

    try:
        page.goto(
            f"{BASE_URL}/web/wreward/category/{web_code}",
            wait_until="domcontentloaded",
            timeout=20000,
        )
        time.sleep(2)
    except Exception as e:
        logger.warning(f"[와디즈/{api_code}] 세션 초기화 실패: {e}")

    for page_num in range(max_pages):
        start_num = page_num * PAGE_SIZE
        try:
            resp = page.request.post(
                API_URL,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Referer": f"{BASE_URL}/web/wreward/category/{web_code}",
                    "Origin": BASE_URL,
                },
                data=json.dumps({
                    "categoryCode": api_code,
                    "endYn": "",
                    "order": "recommend",
                    "limit": PAGE_SIZE,
                    "isMakerClub": False,
                    "startNum": start_num,
                }),
            )
            raw = resp.json()
        except Exception as e:
            logger.warning(f"[와디즈/{api_code}] 페이지 {page_num + 1} 실패: {e}")
            break

        data = raw.get("data", {})
        if not isinstance(data, dict):
            break
        lst = data.get("list", [])
        total_count = data.get("count", 0)

        if not lst:
            logger.info(f"[와디즈/{api_code}] 페이지 {page_num + 1}: 데이터 없음 → 종료")
            break

        new_count = 0
        for item in lst:
            proj = _parse_project(item)
            if not proj:
                continue
            cid = proj.get("campaign_id") or proj["link"]
            if cid in seen_ids:
                continue
            seen_ids.add(cid)
            proj["wadiz_category"] = api_code
            projects.append(proj)
            new_count += 1

        logger.info(
            f"[와디즈/{api_code}] [{page_num + 1}/{max_pages}] {new_count}개 수집 "
            f"(누계 {len(projects)}/{total_count})"
        )

        if start_num + PAGE_SIZE >= total_count:
            logger.info(f"[와디즈/{api_code}] 마지막 페이지 도달")
            break

        time.sleep(random.uniform(delay_min, delay_max))

    return projects


def collect_wadiz(
    category_codes: list = None,
    max_pages: int = 15,
    output_dir: str = "data/raw",
    delay_min: float = 2.0,
    delay_max: float = 4.0,
) -> list:
    """
    와디즈 굿즈 카테고리 전체 수집
    출력: data/raw/wadiz_YYYYMMDD.json
    """
    from playwright.sync_api import sync_playwright

    category_codes = category_codes or CATEGORY_CODES
    date_str = datetime.now().strftime("%Y%m%d")
    all_projects = []
    seen_ids = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="ko-KR",
        )
        page = context.new_page()
        page.route(
            "**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf,eot}",
            lambda r: r.abort(),
        )

        for api_code, web_code in category_codes:
            logger.info(f"와디즈 카테고리 {api_code} 수집 시작")
            projects = _collect_category(
                page, api_code, web_code, max_pages, delay_min, delay_max
            )
            for proj in projects:
                cid = proj.get("campaign_id") or proj["link"]
                if cid not in seen_ids:
                    seen_ids.add(cid)
                    all_projects.append(proj)
            logger.info(f"와디즈 카테고리 {api_code} 완료: {len(projects)}개")

        browser.close()

    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"wadiz_{date_str}.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_projects, f, ensure_ascii=False, indent=2)

    logger.info(f"와디즈 수집 완료: {len(all_projects)}개 → {output_path}")
    return all_projects


def _load_categories_from_config(config_path: str = "config.yaml") -> list:
    """config.yaml에서 와디즈 카테고리 코드 로드"""
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        codes = cfg.get("wadiz", {}).get("categories", [])
        # (api_code, web_code) 튜플로 변환 — web_code는 CATEGORY_CODES에서 매핑
        code_map = {c[0]: c[1] for c in CATEGORY_CODES}
        return [(c, code_map.get(c, "300")) for c in codes]
    except Exception:
        return CATEGORY_CODES


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
    )
    from dotenv import load_dotenv
    load_dotenv()
    categories = _load_categories_from_config()
    data = collect_wadiz(category_codes=categories, max_pages=3)
    print(f"수집된 프로젝트: {len(data)}개")
    if data:
        s = data[0]
        print(f"  샘플: {s['title']} | 달성률 {s['achieved_rate']}% | 후원자 {s['backers']}명")
