"""
Preprocessor Agent — 펀딩 트렌드 MVP
텀블벅 + 와디즈 원본 데이터 정제 + 굿즈 카테고리 분류 + XSS 방어
출력: data/processed/unified_YYYYMMDD.json
"""

import html
import json
import logging
import os
from collections import Counter
from datetime import datetime
from glob import glob
from typing import Optional

import yaml
from rapidfuzz import fuzz

logger = logging.getLogger(__name__)


def _load_latest(directory: str, prefix: str) -> list:
    pattern = os.path.join(directory, f"{prefix}_*.json")
    files = sorted(glob(pattern), reverse=True)
    if not files:
        return []
    with open(files[0], "r", encoding="utf-8") as f:
        data = json.load(f)
    logger.info(f"{prefix} 로드: {len(data)}개 ({files[0]})")
    return data or []


def _load_goods_categories(config_path: str = "config/goods_categories.yaml") -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg.get("categories", {})


def _classify_goods(title: str, categories: dict) -> str:
    """
    키워드 매칭으로 굿즈 카테고리 분류
    1단계: 직접 포함 (우선)
    2단계: rapidfuzz partial_ratio >= 80
    """
    search_text = title.lower()

    best_category = "기타"
    best_score = 0

    for cat_name, cat_data in categories.items():
        if cat_name == "기타":
            continue
        keywords = cat_data.get("keywords", [])
        for kw in keywords:
            if kw.lower() in search_text:
                return cat_name
            score = fuzz.partial_ratio(kw.lower(), search_text)
            if score > best_score and score >= 80:
                best_score = score
                best_category = cat_name

    return best_category


def _escape_text_fields(item: dict) -> dict:
    """크롤링된 텍스트 필드 html.escape() 처리 (XSS + 프롬프트 인젝션 방어)"""
    text_fields = ["title", "creator"]
    for field in text_fields:
        if field in item and isinstance(item[field], str):
            item[field] = html.escape(item[field])
    return item


def _normalize_project(item: dict, categories: dict) -> Optional[dict]:
    """원본 프로젝트 항목 → 정규화된 dict"""
    raw_title = (item.get("title") or "").strip()
    if not raw_title:
        return None

    # XSS + 프롬프트 인젝션 방어
    title = html.escape(raw_title)
    creator = html.escape((item.get("creator") or "").strip())

    goods_category = _classify_goods(raw_title, categories)

    platform = item.get("platform", "")

    # 플랫폼별 ID 필드 통합
    campaign_id = item.get("campaign_id", "") or item.get("permalink", "")

    return {
        # 기본 정보
        "title": title,
        "creator": creator,
        "link": item.get("link", ""),
        "campaign_id": str(campaign_id),
        "platform": platform,
        # 성과 지표
        "achieved_rate": float(item.get("achieved_rate", 0)),
        "backers": int(item.get("backers", 0)),
        "raised_amount": int(item.get("raised_amount", 0)),
        "goal_amount": int(item.get("goal_amount", 0)),
        "early_success": bool(item.get("early_success", False)),
        "remaining_day": int(item.get("remaining_day", -1)),
        # 일정 (텀블벅 전용 — 와디즈는 None)
        "start_date": item.get("start_date", ""),
        "end_date": item.get("end_date", ""),
        "launch_month": item.get("launch_month"),
        "launch_weekday": item.get("launch_weekday"),
        # 분류
        "goods_category": goods_category,
        "tumblbug_category": item.get("tumblbug_category", ""),
        "wadiz_category": item.get("wadiz_category", ""),
        # 태그
        "tags": item.get("tags", []),
        # 메타
        "collected_at": item.get("collected_at", datetime.now().isoformat()),
    }


def run_preprocessor(
    raw_dir: str = "data/raw",
    output_dir: str = "data/processed",
    config_path: str = "config/goods_categories.yaml",
) -> list:
    """
    전처리 실행 (텀블벅 + 와디즈 통합)
    반환: 정규화된 프로젝트 리스트
    """
    tumblbug_data = _load_latest(raw_dir, "tumblbug")
    wadiz_data = _load_latest(raw_dir, "wadiz")

    combined = tumblbug_data + wadiz_data

    if not combined:
        raise ValueError("전처리 입력 없음 — 수집을 먼저 실행해주세요")

    if not tumblbug_data:
        logger.warning("텀블벅 데이터 없음 — 와디즈 단독 처리 진행")
    if not wadiz_data:
        logger.warning("와디즈 데이터 없음 — 텀블벅 단독 처리 진행")

    categories = _load_goods_categories(config_path)
    logger.info(f"굿즈 분류 카테고리: {len(categories)}개")

    unified = []
    seen_ids = set()
    for item in combined:
        normalized = _normalize_project(item, categories)
        if not normalized:
            continue
        uid = normalized["campaign_id"] or normalized["link"]
        if uid in seen_ids:
            continue
        seen_ids.add(uid)
        unified.append(normalized)

    # 카테고리 분포 로그
    cat_counts = Counter(p["goods_category"] for p in unified)
    logger.info(f"굿즈 분류 결과: {dict(cat_counts.most_common())}")

    # 기타 비율 경고
    total = len(unified)
    etc_count = cat_counts.get("기타", 0)
    if total > 0 and etc_count / total > 0.5:
        logger.warning(
            f"기타 비율 높음: {etc_count}/{total} ({etc_count/total*100:.1f}%)"
            " — goods_categories.yaml 키워드 보강 권장"
        )

    platform_counts = Counter(p["platform"] for p in unified)
    logger.info(f"플랫폼별: {dict(platform_counts)}")

    os.makedirs(output_dir, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d")
    output_path = os.path.join(output_dir, f"unified_{date_str}.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(unified, f, ensure_ascii=False, indent=2)

    logger.info(f"전처리 완료: {len(unified)}개 → {output_path}")
    return unified


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
    )
    from dotenv import load_dotenv
    load_dotenv()
    data = run_preprocessor()
    print(f"전처리 완료: {len(data)}개")
    if data:
        s = data[0]
        print(f"  샘플: {s['title']} | 굿즈분류 {s['goods_category']} | 플랫폼 {s['platform']}")
