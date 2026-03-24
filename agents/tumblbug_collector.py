"""
Tumblbug Collector Agent — 펀딩 트렌드 MVP
텀블벅 굿즈/라이프스타일 카테고리 수집 (Playwright + 내부 JSON API)

수집 대상 카테고리:
  character-and-goods: 캐릭터·굿즈
  design-stationery:   디자인·문구
  food:                푸드
  tech:                테크·가전

출력: data/raw/tumblbug_YYYYMMDD.json
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

BASE_URL = "https://tumblbug.com"
API_BASE = "https://tumblbug.com/api/v2/projects"

CATEGORIES = ["character-and-goods", "design-stationery", "food", "tech"]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]


def _parse_rate(text) -> float:
    try:
        if isinstance(text, (int, float)):
            return float(text)
        return float(str(text).replace("%", "").replace(",", "").strip())
    except (ValueError, AttributeError):
        return 0.0


def _parse_int(text) -> int:
    try:
        if isinstance(text, int):
            return text
        return int("".join(filter(str.isdigit, str(text))))
    except (ValueError, TypeError):
        return 0


def _parse_project_from_api(item: dict) -> Optional[dict]:
    """API 응답 항목 → 프로젝트 dict"""
    try:
        title = item.get("title", "").strip()
        if not title:
            return None

        permalink = item.get("permalink", "")
        link = urljoin(BASE_URL, f"/projects/{permalink}") if permalink else ""

        achieved_rate = _parse_rate(item.get("percentage", 0))
        backers = _parse_int(item.get("pledgedCount", 0))

        try:
            raised_amount = int(item.get("amount", 0) or 0)
        except (ValueError, TypeError):
            raised_amount = 0

        end_date = item.get("endDate", "")
        start_date = item.get("startDate", "")

        launch_month = None
        launch_weekday = None
        if start_date:
            try:
                dt = datetime.fromisoformat(start_date[:10])
                launch_month = dt.month
                launch_weekday = dt.strftime("%A")
            except Exception:
                pass

        tags = []
        if item.get("categoryName"):
            tags.append(item["categoryName"])

        return {
            "title": title,
            "creator": item.get("creatorName", ""),
            "link": link,
            "permalink": permalink,
            "platform": "tumblbug",
            "achieved_rate": min(float(achieved_rate), 9999.0),
            "backers": backers,
            "raised_amount": raised_amount,
            "goal_amount": 0,        # API 미제공
            "early_success": False,  # Preprocessor에서 추정
            "end_date": end_date,
            "start_date": start_date,
            "launch_month": launch_month,
            "launch_weekday": launch_weekday,
            "rewards": [],
            "reward_count": 0,
            "min_reward_price": 0,
            "max_reward_price": 0,
            "tags": tags,
            "goods_category": "",    # Preprocessor에서 분류
            "collected_at": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.debug(f"항목 파싱 오류: {e}")
        return None


def _fetch_category(
    category: str,
    max_pages: int = 15,
    delay_min: float = 2.0,
    delay_max: float = 4.0,
) -> list:
    """Playwright으로 텀블벅 단일 카테고리 수집"""
    from playwright.sync_api import sync_playwright

    projects = []
    seen_permalinks = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context = browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            locale="ko-KR",
            extra_http_headers={"Accept-Language": "ko-KR,ko;q=0.9"},
        )
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = context.new_page()
        page.route(
            "**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf,eot}",
            lambda r: r.abort(),
        )

        discover_url = f"{BASE_URL}/discover?category={category}&sort=popular"
        try:
            page.goto(discover_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(2)
        except Exception as e:
            logger.warning(f"[텀블벅/{category}] 세션 초기화 실패: {e}")

        for page_num in range(1, max_pages + 1):
            api_url = f"{API_BASE}?category={category}&projectSort=popular&page={page_num}"
            try:
                resp = page.request.get(
                    api_url,
                    headers={
                        "Accept": "application/json, text/plain, */*",
                        "Referer": discover_url,
                    },
                )
                raw = resp.json()
            except Exception as e:
                logger.warning(f"[텀블벅/{category}] 페이지 {page_num} API 실패: {e}")
                break

            body = raw.get("body", {})
            result = body.get("result", {}) if isinstance(body, dict) else {}
            contents = result.get("contents", []) if isinstance(result, dict) else []

            if not contents:
                logger.info(f"[텀블벅/{category}] 페이지 {page_num}: 데이터 없음 → 종료")
                break

            new_count = 0
            for item in contents:
                proj = _parse_project_from_api(item)
                if not proj:
                    continue
                perm = proj.get("permalink") or proj["link"]
                if perm in seen_permalinks:
                    continue
                seen_permalinks.add(perm)
                proj["tumblbug_category"] = category
                projects.append(proj)
                new_count += 1

            has_next = result.get("hasNext", False)
            logger.info(
                f"[텀블벅/{category}] [{page_num}/{max_pages}] {new_count}개 수집 "
                f"(누계 {len(projects)}, hasNext={has_next})"
            )

            if not has_next:
                break

            time.sleep(random.uniform(delay_min, delay_max))

        browser.close()

    return projects


def collect_tumblbug(
    categories: list = None,
    max_pages: int = 15,
    output_dir: str = "data/raw",
    delay_min: float = 2.0,
    delay_max: float = 4.0,
) -> list:
    """
    텀블벅 굿즈 카테고리 전체 수집
    출력: data/raw/tumblbug_YYYYMMDD.json
    """
    categories = categories or CATEGORIES
    date_str = datetime.now().strftime("%Y%m%d")
    all_projects = []
    seen_permalinks = set()

    for category in categories:
        logger.info(f"텀블벅 카테고리 {category} 수집 시작")
        try:
            projects = _fetch_category(category, max_pages, delay_min, delay_max)
        except Exception as e:
            logger.warning(f"텀블벅 카테고리 {category} 수집 실패: {e}")
            projects = []

        for proj in projects:
            perm = proj.get("permalink") or proj["link"]
            if perm not in seen_permalinks:
                seen_permalinks.add(perm)
                all_projects.append(proj)

        logger.info(f"텀블벅 카테고리 {category} 완료: {len(projects)}개")

    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"tumblbug_{date_str}.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_projects, f, ensure_ascii=False, indent=2)

    logger.info(f"텀블벅 수집 완료: {len(all_projects)}개 → {output_path}")
    return all_projects


def _load_categories_from_config(config_path: str = "config.yaml") -> list:
    """config.yaml에서 텀블벅 카테고리 로드"""
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        enabled = cfg.get("tumblbug", {}).get("enabled", True)
        if not enabled:
            logger.info("config.yaml: tumblbug.enabled=false — 수집 건너뜀")
            return []
        return cfg.get("tumblbug", {}).get("categories", CATEGORIES)
    except Exception:
        return CATEGORIES


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
    )
    from dotenv import load_dotenv
    load_dotenv()
    categories = _load_categories_from_config()
    data = collect_tumblbug(categories=categories, max_pages=3)
    print(f"수집된 프로젝트: {len(data)}개")
    if data:
        s = data[0]
        print(f"  샘플: {s['title']} | 달성률 {s['achieved_rate']}% | 후원자 {s['backers']}명")
