"""
Launch Advisor Agent — 펀딩 트렌드 MVP
트렌드 분석 결과를 바탕으로 상품 컨셉 + 펀딩 페이지 HTML + SNS 카피 자동 생성

파이프라인:
  Step1: trend_analysis → concepts JSON (3개)
  Step2: concepts top1 → 펀딩 페이지 HTML  ─┐ 병렬 (ThreadPoolExecutor)
  Step3: concepts top1 → SNS 카피            ─┘

top1 선택 기준: expected_success_rate 최대값 (config: top_concept_metric)

출력:
  data/reports/concepts_YYYYMMDD.json
  data/pages/funding_page_YYYYMMDD.html
  data/pages/sns_copy_YYYYMMDD.json
"""

import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from glob import glob
from typing import Optional

from utils.claude_client import call_claude

logger = logging.getLogger(__name__)

HTML_MIN_LENGTH = 3000  # 최소 HTML 길이 (미달 시 재시도)


def _load_latest(directory: str, prefix: str) -> Optional[dict]:
    pattern = os.path.join(directory, f"{prefix}_*.json")
    files = sorted(glob(pattern), reverse=True)
    if not files:
        return None
    with open(files[0], "r", encoding="utf-8") as f:
        return json.load(f)


def _build_concepts_prompt(analysis: dict, concepts_count: int = 3) -> str:
    summary = analysis.get("summary", {})
    by_cat = analysis.get("by_goods_category", {})
    top_projects = analysis.get("top_projects", [])[:5]
    saturation = analysis.get("saturation_warnings", [])

    hot_cats = sorted(
        by_cat.items(),
        key=lambda x: x[1].get("avg_trend_score", 0),
        reverse=True
    )[:5]

    hot_lines = "\n".join([
        f"  - {cat}: 성공률 {data.get('success_rate_pct', 0)}%, "
        f"TREND_SCORE {data.get('avg_trend_score', 0)}, "
        f"건수 {data.get('count', 0)}건"
        for cat, data in hot_cats
    ])

    top_lines = "\n".join([
        f"  {i+1}. {p['title'][:40]} — {p.get('goods_category', '기타')}, "
        f"달성률 {p.get('achieved_rate', 0)}%, 후원자 {p.get('backers', 0)}명"
        for i, p in enumerate(top_projects)
    ])

    red_ocean = (
        ", ".join([w["goods_category"] for w in saturation])
        if saturation else "없음"
    )

    return f"""다음은 텀블벅·와디즈 굿즈 펀딩 트렌드 분석 결과입니다.
이 데이터를 기반으로 지금 만들면 잘 팔릴 굿즈 상품 컨셉 {concepts_count}개를 제안해주세요.

## 트렌드 분석 요약
- 총 분석 프로젝트: {summary.get('total_projects', 0)}개
- 전체 성공률: {summary.get('success_rate_pct', 0)}%
- 레드오션 경고 카테고리: {red_ocean}

## HOT 굿즈 카테고리 TOP 5 (TREND_SCORE 순)
{hot_lines}

## 참조 프로젝트 TOP 5
{top_lines}

---
{concepts_count}개의 상품 컨셉을 다음 JSON 배열 형식으로만 반환해주세요.
다른 설명 없이 JSON만 출력하세요:

[
  {{
    "rank": 1,
    "concept_name": "상품 컨셉명 (20자 이내)",
    "goods_category": "굿즈 카테고리",
    "target_audience": "타겟 고객 (2~3줄)",
    "product_description": "상품 설명 (3~5줄)",
    "price_range": "예상 가격 범위 (예: 15,000~25,000원)",
    "funding_goal": "권장 목표금액 (예: 500만원)",
    "expected_success_rate": 75,
    "differentiation": "차별화 포인트 (2~3줄)",
    "trend_basis": "선정 근거 (데이터 기반, 2~3줄)"
  }}
]"""


def _build_html_prompt(concept: dict) -> str:
    return f"""다음 굿즈 상품 컨셉으로 크라우드펀딩 상세 페이지 HTML을 작성해주세요.

## 상품 컨셉
- 상품명: {concept.get('concept_name', '')}
- 카테고리: {concept.get('goods_category', '')}
- 타겟 고객: {concept.get('target_audience', '')}
- 상품 설명: {concept.get('product_description', '')}
- 가격 범위: {concept.get('price_range', '')}
- 목표금액: {concept.get('funding_goal', '')}
- 차별화 포인트: {concept.get('differentiation', '')}

## HTML 요구사항
- 완전한 standalone HTML 문서 (<!DOCTYPE html>부터 </html>까지)
- 라이트 모드 전용 (배경: #ffffff)
- 폰트: Pretendard Variable (CDN: https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/variable/pretendardvariable.css)
- Mobile-first 반응형 (breakpoints: 320px / 768px / 1200px)
- CTA 버튼 최소 44×44px 터치 타깃
- 금지 패턴: 보라 그라디언트 히어로, 맥락없는 3열 아이콘 카드
- 섹션 구성: 히어로 → 상품 소개 → 리워드 구성 → 제작자 소개 → FAQ → CTA

완전한 HTML만 출력하세요. 설명이나 마크다운 코드펜스 없이 HTML 코드만 반환합니다."""


def _build_sns_prompt(concept: dict) -> str:
    return f"""다음 굿즈 펀딩 프로젝트의 SNS 홍보 카피를 작성해주세요.

## 상품 정보
- 상품명: {concept.get('concept_name', '')}
- 카테고리: {concept.get('goods_category', '')}
- 타겟: {concept.get('target_audience', '')}
- 가격: {concept.get('price_range', '')}
- 차별화: {concept.get('differentiation', '')}

## 요청 카피 (JSON 형식으로만 반환)
다른 설명 없이 다음 JSON만 출력하세요:

{{
  "instagram_caption": "인스타그램 캡션 (이모지 포함, 200자 이내, 해시태그 5개)",
  "twitter_post": "트위터/X 포스트 (140자 이내)",
  "kakao_message": "카카오톡 공유 메시지 (3줄 이내)",
  "launch_hook": "펀딩 오픈 당일 훅 문구 (한 문장, 30자 이내)"
}}"""


def _parse_json_response(text: str, label: str = "") -> Optional[dict | list]:
    """Claude 응답에서 JSON 추출 (코드펜스 제거 + 정규식 fallback)"""
    if not text:
        return None

    # 코드펜스 제거
    cleaned = re.sub(r"```(?:json)?\s*", "", text).replace("```", "").strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # 배열 추출 시도
    m = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass

    # 객체 추출 시도
    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass

    logger.warning(f"[{label}] JSON 파싱 실패")
    return None


def _select_top_concept(concepts: list, metric: str = "success_rate") -> dict:
    """expected_success_rate 기준 top1 선택"""
    if not concepts:
        return {}
    return max(concepts, key=lambda c: c.get("expected_success_rate", 0))


def run_launch_advisor(
    processed_dir: str = "data/processed",
    output_dir: str = "data/reports",
    pages_dir: str = "data/pages",
    model: str = "claude-sonnet-4-20250514",
    max_tokens: int = 4000,
    concepts_count: int = 3,
) -> Optional[str]:
    """
    Launch Advisor 실행
    반환: concepts JSON 경로 (실패 시 None)
    """
    date_str = datetime.now().strftime("%Y%m%d")

    analysis = _load_latest(processed_dir, "trend_analysis")
    if not analysis:
        raise ValueError("분석 파일 없음 — 분석을 먼저 실행해주세요")

    # ── Step 1: 상품 컨셉 생성 ───────────────────────────────────────
    logger.info("Step1: 상품 컨셉 생성 중...")
    concepts_prompt = _build_concepts_prompt(analysis, concepts_count)
    concepts_text = call_claude(concepts_prompt, model=model, max_tokens=max_tokens)

    if not concepts_text:
        logger.error("Step1: Claude API 실패 — launch_advisor 중단")
        return None

    concepts = _parse_json_response(concepts_text, label="concepts")
    if not concepts or not isinstance(concepts, list):
        logger.error("Step1: 컨셉 JSON 파싱 실패 — launch_advisor 중단")
        return None

    logger.info(f"Step1 완료: {len(concepts)}개 컨셉 생성")

    os.makedirs(output_dir, exist_ok=True)
    concepts_path = os.path.join(output_dir, f"concepts_{date_str}.json")
    with open(concepts_path, "w", encoding="utf-8") as f:
        json.dump(concepts, f, ensure_ascii=False, indent=2)

    # ── top1 선택 ────────────────────────────────────────────────────
    top_concept = _select_top_concept(concepts)
    if not top_concept:
        logger.error("컨셉 top1 선택 실패")
        return concepts_path

    logger.info(f"Top1 컨셉: {top_concept.get('concept_name')} "
                f"(expected_success_rate={top_concept.get('expected_success_rate')}%)")

    # ── Step 2 + 3: HTML + SNS 카피 병렬 생성 ────────────────────────
    logger.info("Step2+3: 펀딩 페이지 HTML + SNS 카피 병렬 생성 중...")

    html_prompt = _build_html_prompt(top_concept)
    sns_prompt = _build_sns_prompt(top_concept)

    html_content = None
    sns_content = None

    def _gen_html():
        return call_claude(html_prompt, model=model, max_tokens=max_tokens)

    def _gen_sns():
        return call_claude(sns_prompt, model=model, max_tokens=1000)

    with ThreadPoolExecutor(max_workers=2) as executor:
        f_html = executor.submit(_gen_html)
        f_sns = executor.submit(_gen_sns)

        for future, label in [(f_html, "html"), (f_sns, "sns")]:
            try:
                result = future.result()
                if label == "html":
                    html_content = result
                else:
                    sns_content = result
            except Exception as e:
                logger.error(f"Step {'2' if label == 'html' else '3'} [{label}] 실패: {e}")

    # ── HTML 저장 ─────────────────────────────────────────────────────
    os.makedirs(pages_dir, exist_ok=True)

    if html_content:
        # 최소 길이 검증
        if len(html_content) < HTML_MIN_LENGTH:
            logger.warning(
                f"HTML 길이 미달 ({len(html_content)} < {HTML_MIN_LENGTH}) — "
                "단독 재시도 1회"
            )
            html_retry = call_claude(html_prompt, model=model, max_tokens=max_tokens)
            if html_retry and len(html_retry) >= HTML_MIN_LENGTH:
                html_content = html_retry
            else:
                logger.warning("HTML 재시도 후에도 미달 — 원본 사용")

        html_path = os.path.join(pages_dir, f"funding_page_{date_str}.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        logger.info(f"펀딩 페이지 저장: {html_path} ({len(html_content)}자)")
    else:
        logger.error("Step2: HTML 생성 실패")

    # ── SNS 카피 저장 ─────────────────────────────────────────────────
    if sns_content:
        sns_data = _parse_json_response(sns_content, label="sns")
        if not sns_data:
            sns_data = {"raw": sns_content}

        sns_path = os.path.join(pages_dir, f"sns_copy_{date_str}.json")
        with open(sns_path, "w", encoding="utf-8") as f:
            json.dump({
                "concept_name": top_concept.get("concept_name"),
                "date": date_str,
                "copy": sns_data,
            }, f, ensure_ascii=False, indent=2)
        logger.info(f"SNS 카피 저장: {sns_path}")
    else:
        logger.error("Step3: SNS 카피 생성 실패")

    logger.info(f"launch_advisor 완료 → {concepts_path}")
    return concepts_path


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
    )
    from dotenv import load_dotenv
    load_dotenv(override=True)
    path = run_launch_advisor()
    print(f"결과: {path}")
