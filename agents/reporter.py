"""
Reporter Agent — 펀딩 트렌드 MVP
분석 결과를 Claude API로 전달해 주간 굿즈 트렌드 리포트 생성
출력: data/reports/weekly_report_YYYYMMDD.md + .json
"""

import json
import logging
import os
from datetime import datetime
from glob import glob
from typing import Optional

from utils.claude_client import call_claude

logger = logging.getLogger(__name__)


def _load_latest(directory: str, prefix: str) -> Optional[dict]:
    pattern = os.path.join(directory, f"{prefix}_*.json")
    files = sorted(glob(pattern), reverse=True)
    if not files:
        return None
    with open(files[0], "r", encoding="utf-8") as f:
        return json.load(f)


def _build_prompt(analysis: dict) -> str:
    summary = analysis.get("summary", {})
    by_cat = analysis.get("by_goods_category", {})
    top = analysis.get("top_projects", [])[:5]
    early = analysis.get("early_success_projects", [])[:3]
    by_platform = analysis.get("by_platform", {})
    saturation = analysis.get("saturation_warnings", [])

    cat_lines = "\n".join([
        f"  - {cat}: 성공률 {data.get('success_rate_pct', 0)}%, "
        f"평균 달성률 {data.get('achieved_rate', {}).get('mean', 0)}%, "
        f"건수 {data.get('count', 0)}건, 트렌드점수 {data.get('avg_trend_score', 0)}"
        for cat, data in sorted(
            by_cat.items(),
            key=lambda x: x[1].get("avg_trend_score", 0),
            reverse=True
        )[:8]
    ])

    top_lines = "\n".join([
        f"  {i+1}. {p['title'][:40]} — 달성률 {p.get('achieved_rate', 0)}%, "
        f"후원자 {p.get('backers', 0)}명, 분류: {p.get('goods_category', '기타')}, "
        f"플랫폼: {p.get('platform', '-')}"
        for i, p in enumerate(top)
    ])

    platform_lines = "\n".join([
        f"  - {platform}: {data.get('count', 0)}건, 성공률 {data.get('success_rate_pct', 0)}%"
        for platform, data in by_platform.items()
    ])

    saturation_lines = (
        ", ".join([w["goods_category"] for w in saturation])
        if saturation else "없음"
    )

    return f"""다음은 텀블벅·와디즈 굿즈 펀딩 프로젝트 데이터 분석 결과입니다.
이 데이터를 바탕으로 굿즈 제작자와 크리에이터를 위한 실용적인 주간 트렌드 리포트를 작성해주세요.

## 수집 개요
- 총 프로젝트: {summary.get('total_projects', 0)}개
- 전체 성공률: {summary.get('success_rate_pct', 0)}%
- 평균 달성률: {summary.get('avg_achieved_rate', 0)}%
- 평균 후원자 수: {summary.get('avg_backers', 0)}명
- 조기 달성 프로젝트: {summary.get('early_success_count', 0)}건
- 플랫폼 구성:
{platform_lines}
- 레드오션 경고 카테고리: {saturation_lines}

## 굿즈 카테고리별 성과 (TREND_SCORE 순)
{cat_lines}

## 이번 주 주목할 프로젝트 TOP 5
{top_lines}

---
아래 6개 섹션으로 리포트를 작성해주세요:

1. 이번 주 HOT 굿즈 상품 TOP 5 (TREND_SCORE 기준, 각 카테고리별 1줄 상품 전략 코멘트)
2. 가격대 분석 (평균 달성률과 후원자 수 기준으로 달콤한 가격 포인트 분석)
3. 텀블벅 vs 와디즈 비교 (각 플랫폼의 특징과 굿즈 유형별 적합성)
4. 조기 달성 프로젝트의 공통 패턴 (무엇이 후원자를 빠르게 모았나)
5. 레드오션 경고 및 블루오션 기회 분석
6. 지금 만들면 잘 팔릴 굿즈 추천 3가지 (근거 포함, 각 2~3줄)

한국어로 작성하고, 데이터 기반의 구체적인 수치를 포함해주세요.
굿즈 제작자가 실제로 활용할 수 있는 실전 인사이트 중심으로 작성해주세요."""


def _build_fallback_report(analysis: dict) -> str:
    summary = analysis.get("summary", {})
    by_cat = analysis.get("by_goods_category", {})
    date_str = datetime.now().strftime("%Y년 %m월 %d일")

    cat_section = "\n".join([
        f"- **{cat}**: 성공률 {data.get('success_rate_pct', 0)}% / "
        f"건수 {data.get('count', 0)}건 / 트렌드점수 {data.get('avg_trend_score', 0)}"
        for cat, data in sorted(
            by_cat.items(),
            key=lambda x: x[1].get("avg_trend_score", 0),
            reverse=True
        )[:6]
    ])

    return f"""# 굿즈 펀딩 트렌드 리포트 ({date_str})
> ⚠️ Claude API 연결 실패 — 수치 기반 리포트 (LLM 코멘트 없음)

## 전체 요약
- 분석 프로젝트: {summary.get('total_projects', 0)}개
- 전체 성공률: {summary.get('success_rate_pct', 0)}%
- 평균 달성률: {summary.get('avg_achieved_rate', 0)}%
- 조기 달성: {summary.get('early_success_count', 0)}건

## 굿즈 카테고리별 TREND_SCORE TOP 6
{cat_section}
"""


def run_reporter(
    processed_dir: str = "data/processed",
    output_dir: str = "data/reports",
    model: str = "claude-sonnet-4-20250514",
    max_tokens: int = 2000,
) -> str:
    date_str = datetime.now().strftime("%Y%m%d")

    analysis = _load_latest(processed_dir, "trend_analysis")
    if not analysis:
        raise ValueError("분석 파일 없음 — 분석을 먼저 실행해주세요")

    prompt = _build_prompt(analysis)
    content = call_claude(prompt, model=model, max_tokens=max_tokens)

    if not content:
        logger.warning("Claude API 실패 — 수치 기반 기본 리포트 생성")
        content = _build_fallback_report(analysis)

    date_label = datetime.now().strftime("%Y년 %m월 %d일")
    report_md = f"""# 굿즈 펀딩 트렌드 리포트 ({date_label})
*생성일: {datetime.now().isoformat()} | 모델: {model}*

---

{content}
"""

    os.makedirs(output_dir, exist_ok=True)
    md_path = os.path.join(output_dir, f"weekly_report_{date_str}.md")
    json_path = os.path.join(output_dir, f"weekly_report_{date_str}.json")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(report_md)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "date": date_str,
            "model": model,
            "summary": analysis.get("summary", {}),
            "report_md": report_md,
        }, f, ensure_ascii=False, indent=2)

    logger.info(f"리포트 생성 완료 → {md_path}")
    return md_path


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
    )
    from dotenv import load_dotenv
    load_dotenv(override=True)
    path = run_reporter()
    print(f"리포트: {path}")
