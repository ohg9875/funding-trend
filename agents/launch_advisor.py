"""
Launch Advisor Agent — 펀딩 트렌드 MVP
트렌드 분석 결과를 바탕으로 실제 데이터 기반 기획서 + 플랫폼 등록 초안 자동 생성

파이프라인:
  Step1: trend_analysis → concepts JSON (3개)
  Step2: top1 컨셉 + 실제 유사 성공 사례 → 기획서 (MD)  ─┐ 병렬
  Step3: top1 컨셉 + 실제 유사 성공 사례 → 등록 초안 (MD) ─┤
  Step4: top1 컨셉 + SNS 카피 (JSON)                       ─┘
  Step5: 기획서 + 등록 초안 → GitHub Pages용 HTML (실제 수치)

top1 선택 기준: expected_success_rate 최대값

출력:
  data/reports/concepts_YYYYMMDD.json
  data/reports/planning_YYYYMMDD.md      ← 내부 기획서 (실제 수치 기반)
  data/reports/launch_draft_YYYYMMDD.md  ← 플랫폼 등록 초안
  data/pages/funding_page_YYYYMMDD.html  ← GitHub Pages (실제 수치 기반)
  data/pages/sns_copy_YYYYMMDD.json
"""

import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from glob import glob
from typing import Optional

from utils.claude_client import call_claude

logger = logging.getLogger(__name__)

HTML_MIN_LENGTH = 3000


# ── 데이터 로더 ──────────────────────────────────────────────────────────────

def _load_latest(directory: str, prefix: str) -> Optional[dict]:
    pattern = os.path.join(directory, f"{prefix}_*.json")
    files = sorted(glob(pattern), reverse=True)
    if not files:
        return None
    with open(files[0], "r", encoding="utf-8") as f:
        return json.load(f)


def _load_latest_list(directory: str, prefix: str) -> list:
    """unified_*.json 같은 리스트 JSON 로드"""
    pattern = os.path.join(directory, f"{prefix}_*.json")
    files = sorted(glob(pattern), reverse=True)
    if not files:
        return []
    with open(files[0], "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def _get_similar_projects(processed_dir: str, goods_category: str, top_n: int = 5) -> list:
    """실제 수집 데이터에서 동일 카테고리 성공 사례 추출"""
    all_projects = _load_latest_list(processed_dir, "unified")
    if not all_projects:
        return []
    similar = [
        p for p in all_projects
        if p.get("goods_category") == goods_category and p.get("achieved_rate", 0) >= 100
    ]
    similar.sort(key=lambda x: x.get("achieved_rate", 0), reverse=True)
    return similar[:top_n]


# ── 프롬프트 빌더 ────────────────────────────────────────────────────────────

def _build_concepts_prompt(analysis: dict, concepts_count: int = 3) -> str:
    summary = analysis.get("summary", {})
    by_cat = analysis.get("by_goods_category", {})
    top_projects = analysis.get("top_projects", [])[:5]
    saturation = analysis.get("saturation_warnings", [])

    hot_cats = sorted(
        by_cat.items(),
        key=lambda x: x[1].get("avg_trend_score", 0),
        reverse=True,
    )[:5]

    hot_lines = "\n".join(
        f"  - {cat}: 트렌드점수 {d.get('avg_trend_score', 0):.1f}, "
        f"성공률 {d.get('success_rate', 0):.0f}%, "
        f"평균달성률 {d.get('avg_achieved_rate', 0):.0f}%, "
        f"평균후원자 {d.get('avg_backers', 0):.0f}명"
        for cat, d in hot_cats
    )

    top_lines = "\n".join(
        f"  - {p.get('title', '')} | {p.get('goods_category', '')} | "
        f"달성률 {p.get('achieved_rate', 0):.0f}% | 후원자 {p.get('backers', 0)}명"
        for p in top_projects
    )

    saturation_text = "\n".join(f"  - {w}" for w in saturation) if saturation else "  없음"

    return f"""당신은 크라우드펀딩 굿즈 트렌드 전문가입니다.
아래 이번 주 실제 수집·분석 데이터를 바탕으로 신규 펀딩 상품 컨셉을 제안해주세요.

## 이번 주 수집 현황
- 총 수집 프로젝트: {summary.get('total_projects', 0)}개
- 분석 기간: {summary.get('collected_at', '이번 주')}

## HOT 굿즈 카테고리 TOP 5 (TREND_SCORE 순)
{hot_lines}

## 참조 프로젝트 TOP 5
{top_lines}

## 포화 경고 카테고리
{saturation_text}

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


def _format_similar_projects(projects: list) -> str:
    if not projects:
        return "수집된 동일 카테고리 성공 사례 없음"
    lines = []
    for p in projects:
        min_r = p.get("min_reward_price", 0)
        max_r = p.get("max_reward_price", 0)
        price_str = f"{min_r:,}~{max_r:,}원" if min_r and max_r else (f"{min_r:,}원~" if min_r else "가격정보 없음")
        lines.append(
            f"- {p.get('title', '')} | 달성률 {p.get('achieved_rate', 0):.0f}% | "
            f"후원자 {p.get('backers', 0):,}명 | 리워드 {price_str}"
        )
    return "\n".join(lines)


def _build_planning_prompt(concept: dict, similar_projects: list, analysis: dict) -> str:
    cat = concept.get("goods_category", "")
    cat_data = analysis.get("by_goods_category", {}).get(cat, {})
    wow = analysis.get("week_over_week", {}).get(cat, {})
    projects_text = _format_similar_projects(similar_projects)

    return f"""당신은 크라우드펀딩 전문 기획자입니다.
아래 실제 수집 데이터를 근거로 내부 검토용 기획서를 작성해주세요.
모든 수치는 반드시 아래 실제 데이터에서 인용하세요. 근거 없는 수치를 만들지 마세요.

## 트렌드 분석 데이터 (실제 수집)
- 카테고리: {cat}
- 트렌드 점수: {cat_data.get('avg_trend_score', 0):.1f}점
- 전주 대비: {wow.get('delta', 0):+.1f}점 ({wow.get('direction', 'flat')})
- 카테고리 평균 달성률: {cat_data.get('achieved_rate', {}).get('mean', 0):.0f}%
- 카테고리 평균 후원자: {cat_data.get('backers', {}).get('mean', 0):.0f}명
- 펀딩 성공률(100% 달성): {cat_data.get('success_rate_pct', 0):.0f}%
- 이번 주 신규 프로젝트 수: {cat_data.get('count', 0)}개

## 동일 카테고리 실제 성공 사례 (이번 주 수집)
{projects_text}

## 제안 상품 컨셉
- 상품명: {concept.get('concept_name', '')}
- 타겟: {concept.get('target_audience', '')}
- 설명: {concept.get('product_description', '')}
- 가격대: {concept.get('price_range', '')}
- 목표금액: {concept.get('funding_goal', '')}
- 차별화: {concept.get('differentiation', '')}
- 선정 근거: {concept.get('trend_basis', '')}

---
다음 구조로 마크다운 기획서를 작성하세요:

# {concept.get('concept_name', '상품명')} — 크라우드펀딩 기획서

## 1. 기회 근거
(트렌드 점수·전주 대비 변화를 인용해 왜 지금 이 아이템인지 설명)

## 2. 시장 현황
(위 실제 성공 사례를 분석 — 달성률 범위, 후원자 규모, 리워드 가격대 패턴)

## 3. 상품 전략
(가격 포지셔닝, 리워드 구성 전략 — 성공 사례 수치 기반 근거 포함)

## 4. 예상 수치 (성공 사례 기반)
- 추천 목표금액: (근거 포함)
- 추천 최저 리워드: (근거 포함)
- 예상 달성률 범위: (카테고리 평균 기반)
- 예상 후원자 수: (카테고리 평균 기반)

## 5. 리스크 & 대응
- 포화도: (신규 프로젝트 수 기반)
- 경쟁 리스크: (성공 사례 분석 기반)
- 대응 전략:

## 6. GO / NO-GO 권고
**GO** 또는 **NO-GO** — 한 문장 근거 (반드시 실제 수치 인용)"""


def _build_draft_prompt(concept: dict, similar_projects: list) -> str:
    projects_text = _format_similar_projects(similar_projects[:3])

    return f"""당신은 크라우드펀딩 플랫폼(텀블벅·와디즈) 등록 전문가입니다.
아래 정보를 바탕으로 실제 등록 가능한 프로젝트 초안을 작성해주세요.

## 상품 컨셉
- 상품명: {concept.get('concept_name', '')}
- 카테고리: {concept.get('goods_category', '')}
- 타겟: {concept.get('target_audience', '')}
- 설명: {concept.get('product_description', '')}
- 가격대: {concept.get('price_range', '')}
- 차별화: {concept.get('differentiation', '')}

## 참고 성공 사례 (실제 수집)
{projects_text}

---
다음 구조로 마크다운 초안을 작성하세요:

# 텀블벅 / 와디즈 등록 초안

## 프로젝트 제목 후보 (3개)
1.
2.
3.

## 한 줄 소개 (50자 이내)

## 프로젝트 스토리 (본문)
(실제 등록 가능 수준. 최소 600자. 왜 이 상품인지, 누구를 위한지, 특징, 제작 스토리)

## 리워드 구성
| 등급 | 가격 | 구성품 | 한정 수량 |
|------|------|--------|-----------|
| 얼리버드 | | | 100개 |
| 기본 | | 제한 없음 |
| 스페셜 | | | 50개 |

## 태그 / 키워드 (5개)

## FAQ
**Q. 배송은 언제 시작되나요?**
A.

**Q. 펀딩 미달성 시 어떻게 되나요?**
A. 목표금액 미달성 시 결제가 진행되지 않으며 전액 환불됩니다.

**Q. 교환·환불 정책은?**
A."""


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


def _build_comparison_rows(all_concepts: list, analysis: dict) -> str:
    """3개 컨셉 비교 표 HTML 행 생성"""
    rows = []
    by_cat = analysis.get("by_goods_category", {})
    for i, c in enumerate(all_concepts):
        cat = c.get("goods_category", "")
        cat_data = by_cat.get(cat, {})
        score = cat_data.get("avg_trend_score", 0)
        count = cat_data.get("count", 0)
        saturation = "낮음" if count <= 5 else ("중간" if count <= 20 else "높음")
        saturation_color = "#38A169" if count <= 5 else ("#D97706" if count <= 20 else "#E53E3E")
        badge = ' <span style="background:#FF5A1F;color:#fff;font-size:.65rem;padding:2px 6px;border-radius:10px;vertical-align:middle">1위</span>' if i == 0 else ""
        rows.append(
            f'<tr{"style=\"background:#FFF8F6\"" if i == 0 else ""}>'
            f'<td><strong>{c.get("concept_name", "")}</strong>{badge}</td>'
            f'<td style="text-align:center">{c.get("goods_category", "")}</td>'
            f'<td style="text-align:center;color:#FF5A1F;font-weight:700">{score:.0f}점</td>'
            f'<td style="text-align:center">{c.get("expected_success_rate", 0)}%</td>'
            f'<td style="text-align:center;color:{saturation_color}">{saturation} ({count}건)</td>'
            f'<td style="text-align:center">{c.get("price_range", "-")}</td>'
            f'</tr>'
        )
    return "\n".join(rows)


def _build_html_from_reports(concept: dict, planning_md: str, draft_md: str, analysis: dict, all_concepts: list = None) -> str:
    """기획서 + 등록 초안을 GitHub Pages용 HTML로 변환 (실제 수치 기반)"""
    cat = concept.get("goods_category", "")
    cat_data = analysis.get("by_goods_category", {}).get(cat, {})
    wow = analysis.get("week_over_week", {}).get(cat, {})
    direction_symbol = {"up": "↑", "down": "↓", "flat": "→"}.get(wow.get("direction", "flat"), "→")
    # 비교 표 블록 (f-string 밖에서 계산 — 중첩 f-string 문제 방지)
    if all_concepts and len(all_concepts) > 1:
        comparison_rows = _build_comparison_rows(all_concepts, analysis)
        comparison_block = (
            '<div class="compare-section">'
            '<h3>이번 주 컨셉 비교</h3>'
            '<table class="compare-table"><thead><tr>'
            '<th>컨셉명</th><th>카테고리</th><th>트렌드 점수</th>'
            '<th>예상 성공률</th><th>경쟁 강도</th><th>가격대</th>'
            '</tr></thead><tbody>'
            + comparison_rows +
            '</tbody></table>'
            '<button class="slack-btn" onclick="copySlackMsg()">'
            '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">'
            '<path d="M5.042 15.165a2.528 2.528 0 0 1-2.52 2.523A2.528 2.528 0 0 1 0 15.165'
            'a2.527 2.527 0 0 1 2.522-2.52h2.52v2.52zM6.313 15.165a2.527 2.527 0 0 1 2.521-2.52'
            ' 2.527 2.527 0 0 1 2.521 2.52v6.313A2.528 2.528 0 0 1 8.834 24a2.528 2.528 0 0 1'
            '-2.521-2.522v-6.313zM8.834 5.042a2.528 2.528 0 0 1-2.521-2.52A2.528 2.528 0 0 1'
            ' 8.834 0a2.528 2.528 0 0 1 2.521 2.522v2.52H8.834zM8.834 6.313a2.528 2.528 0 0 1'
            ' 2.521 2.521 2.528 2.528 0 0 1-2.521 2.521H2.522A2.528 2.528 0 0 1 0 8.834a2.528'
            ' 2.528 0 0 1 2.522-2.521h6.312zM18.956 8.834a2.528 2.528 0 0 1 2.522-2.521A2.528'
            ' 2.528 0 0 1 24 8.834a2.528 2.528 0 0 1-2.522 2.521h-2.522V8.834zM17.688 8.834a2.528'
            ' 2.528 0 0 1-2.523 2.521 2.527 2.527 0 0 1-2.52-2.521V2.522A2.527 2.527 0 0 1 15.165'
            ' 0a2.528 2.528 0 0 1 2.523 2.522v6.312zM15.165 18.956a2.528 2.528 0 0 1 2.523 2.522'
            'A2.528 2.528 0 0 1 15.165 24a2.527 2.527 0 0 1-2.52-2.522v-2.522h2.52zM15.165 17.688'
            'a2.527 2.527 0 0 1-2.52-2.523 2.526 2.526 0 0 1 2.52-2.52h6.313A2.527 2.527 0 0 1 24'
            ' 15.165a2.528 2.528 0 0 1-2.522 2.523h-6.313z"/></svg>'
            ' Slack으로 공유'
            '</button></div>'
        )
    else:
        comparison_block = ""

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>펀딩 트렌드 인사이트 — {concept.get('concept_name', '')}</title>
  <link rel="stylesheet" as="style" crossorigin href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/variable/pretendardvariable.css"/>
  <style>
    :root {{
      --primary: #FF5A1F;
      --surface: #F7F8FA;
      --border: #E2E8F0;
      --text: #1A202C;
      --text-sub: #4A5568;
      --text-muted: #718096;
      --success: #38A169;
    }}
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: 'Pretendard Variable', -apple-system, sans-serif; background: #fff; color: var(--text); line-height: 1.7; word-break: keep-all; }}
    .container {{ max-width: 860px; margin: 0 auto; padding: 0 20px; }}
    header {{ background: var(--text); color: #fff; padding: 20px 0; }}
    header .container {{ display: flex; align-items: center; justify-content: space-between; }}
    header h1 {{ font-size: 1rem; font-weight: 600; opacity: .85; }}
    header .date {{ font-size: .8rem; opacity: .5; }}
    .hero {{ background: var(--surface); border-bottom: 1px solid var(--border); padding: 48px 0 36px; }}
    .hero h2 {{ font-size: 1.953rem; font-weight: 700; margin-bottom: 8px; }}
    .hero .category {{ display: inline-block; background: var(--primary); color: #fff; font-size: .75rem; font-weight: 600; padding: 3px 10px; border-radius: 20px; margin-bottom: 16px; }}
    .stats {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; margin-top: 28px; }}
    @media(min-width: 600px) {{ .stats {{ grid-template-columns: repeat(4, 1fr); }} }}
    .stat-card {{ background: #fff; border: 1px solid var(--border); border-radius: 12px; padding: 16px; text-align: center; }}
    .stat-card .val {{ font-size: 1.563rem; font-weight: 700; color: var(--primary); }}
    .stat-card .lbl {{ font-size: .75rem; color: var(--text-muted); margin-top: 4px; }}
    .wow {{ font-size: .8rem; color: var(--success); font-weight: 600; }}
    .tabs {{ display: flex; border-bottom: 2px solid var(--border); margin: 36px 0 0; }}
    .tab {{ padding: 12px 20px; font-size: .95rem; font-weight: 600; color: var(--text-muted); cursor: pointer; border-bottom: 2px solid transparent; margin-bottom: -2px; transition: .2s; }}
    .tab.active {{ color: var(--primary); border-bottom-color: var(--primary); }}
    .tab-content {{ display: none; padding: 32px 0 60px; }}
    .tab-content.active {{ display: block; }}
    .compare-section {{ padding: 32px 0 8px; }}
    .compare-section h3 {{ font-size: 1rem; font-weight: 700; margin-bottom: 12px; }}
    .compare-table {{ width: 100%; border-collapse: collapse; font-size: .875rem; }}
    .compare-table th {{ background: var(--surface); padding: 10px 12px; text-align: left; font-weight: 600; border: 1px solid var(--border); color: var(--text-muted); font-size: .75rem; }}
    .compare-table td {{ padding: 10px 12px; border: 1px solid var(--border); }}
    .slack-btn {{ display: inline-flex; align-items: center; gap: 8px; background: #4A154B; color: #fff; border: none; padding: 10px 20px; border-radius: 8px; font-size: .875rem; font-weight: 600; cursor: pointer; margin-top: 16px; transition: opacity .15s; }}
    .slack-btn:hover {{ opacity: .85; }}
    .toast {{ position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%); background: #1A202C; color: #fff; padding: 10px 20px; border-radius: 8px; font-size: .875rem; opacity: 0; transition: opacity .3s; pointer-events: none; z-index: 200; }}
    .md-body h1 {{ font-size: 1.563rem; font-weight: 700; margin: 32px 0 12px; padding-bottom: 8px; border-bottom: 1px solid var(--border); }}
    .md-body h2 {{ font-size: 1.25rem; font-weight: 700; margin: 28px 0 10px; color: var(--text); }}
    .md-body p {{ margin-bottom: 14px; color: var(--text-sub); }}
    .md-body ul, .md-body ol {{ padding-left: 20px; margin-bottom: 14px; color: var(--text-sub); }}
    .md-body li {{ margin-bottom: 6px; }}
    .md-body strong {{ color: var(--text); }}
    .md-body table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: .9rem; }}
    .md-body th {{ background: var(--surface); padding: 10px 12px; text-align: left; font-weight: 600; border: 1px solid var(--border); }}
    .md-body td {{ padding: 9px 12px; border: 1px solid var(--border); color: var(--text-sub); }}
    .md-body blockquote {{ border-left: 3px solid var(--primary); padding-left: 16px; color: var(--text-muted); margin-bottom: 14px; }}
    .md-body code {{ background: var(--surface); padding: 1px 5px; border-radius: 4px; font-size: .875rem; }}
    footer {{ background: var(--surface); border-top: 1px solid var(--border); padding: 24px 0; text-align: center; font-size: .8rem; color: var(--text-muted); }}
  </style>
</head>
<body>
<header>
  <div class="container">
    <h1>펀딩 트렌드 인사이트</h1>
    <span class="date">{datetime.now().strftime('%Y년 %m월 %d일')}</span>
  </div>
</header>

<div class="hero">
  <div class="container">
    <span class="category">{cat}</span>
    <h2>{concept.get('concept_name', '')}</h2>
    <p style="color:var(--text-sub);max-width:600px;">{concept.get('product_description', '')[:120]}...</p>
    <div class="stats">
      <div class="stat-card">
        <div class="val">{cat_data.get('avg_trend_score', 0):.0f}점</div>
        <div class="lbl">트렌드 점수</div>
        <div class="wow">{direction_symbol} {wow.get('delta', 0):+.1f}</div>
      </div>
      <div class="stat-card">
        <div class="val">{cat_data.get('success_rate_pct', 0):.0f}%</div>
        <div class="lbl">카테고리 성공률</div>
      </div>
      <div class="stat-card">
        <div class="val">{cat_data.get('achieved_rate', {}).get('mean', 0):.0f}%</div>
        <div class="lbl">평균 달성률</div>
      </div>
      <div class="stat-card">
        <div class="val">{cat_data.get('backers', {}).get('mean', 0):.0f}명</div>
        <div class="lbl">평균 후원자</div>
      </div>
    </div>
  </div>
</div>

<div class="container">
  {comparison_block}
  <div class="tabs">
    <div class="tab active" onclick="switchTab('planning', this)">기획서</div>
    <div class="tab" onclick="switchTab('draft', this)">등록 초안</div>
  </div>

  <div id="tab-planning" class="tab-content active">
    <div class="md-body" id="planning-content"></div>
  </div>
  <div id="tab-draft" class="tab-content">
    <div class="md-body" id="draft-content"></div>
  </div>
</div>

<div class="toast" id="toast">복사됐습니다!</div>

<footer>
  <div class="container">펀딩 트렌드 인사이트 MVP · 매주 월요일 자동 업데이트</div>
</footer>

<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<script>
const planningMd = {json.dumps(planning_md, ensure_ascii=False)};
const draftMd = {json.dumps(draft_md, ensure_ascii=False)};

document.getElementById('planning-content').innerHTML = marked.parse(planningMd);
document.getElementById('draft-content').innerHTML = marked.parse(draftMd);

function switchTab(id, el) {{
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
  el.classList.add('active');
  document.getElementById('tab-' + id).classList.add('active');
}}

function copySlackMsg() {{
  const msg = [
    '📊 *펀딩 트렌드 인사이트 — {datetime.now().strftime("%Y년 %m월 %d일")}*',
    '',
    '🥇 *이번 주 TOP 추천 컨셉*',
    '  {concept.get("concept_name", "")} ({cat} · 트렌드 {cat_data.get("avg_trend_score", 0):.0f}점)',
    '  예상 성공률 {concept.get("expected_success_rate", 0)}% · 목표금액 {concept.get("funding_goal", "")}',
    '  가격대: {concept.get("price_range", "")}',
    '',
    '🔗 기획서·등록 초안 보기: https://ohg9875.github.io/funding-trend/',
  ].join('\\n');
  navigator.clipboard.writeText(msg).then(() => {{
    const t = document.getElementById('toast');
    t.style.opacity = '1';
    setTimeout(() => t.style.opacity = '0', 2000);
  }});
}}
</script>
</body>
</html>"""


# ── JSON 파서 ────────────────────────────────────────────────────────────────

def _parse_json_response(text: str, label: str = "") -> Optional[dict | list]:
    if not text:
        return None
    cleaned = re.sub(r"```(?:json)?\s*", "", text).replace("```", "").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    logger.warning(f"[{label}] JSON 파싱 실패")
    return None


def _select_top_concept(concepts: list) -> dict:
    if not concepts:
        return {}
    return max(concepts, key=lambda c: c.get("expected_success_rate", 0))


# ── 메인 실행 ────────────────────────────────────────────────────────────────

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
    concepts_text = call_claude(
        _build_concepts_prompt(analysis, concepts_count),
        model=model, max_tokens=max_tokens,
    )
    if not concepts_text:
        logger.error("Step1: Claude API 실패")
        return None

    concepts = _parse_json_response(concepts_text, label="concepts")
    if not concepts or not isinstance(concepts, list):
        logger.error("Step1: 컨셉 JSON 파싱 실패")
        return None

    logger.info(f"Step1 완료: {len(concepts)}개 컨셉 생성")
    os.makedirs(output_dir, exist_ok=True)
    concepts_path = os.path.join(output_dir, f"concepts_{date_str}.json")
    with open(concepts_path, "w", encoding="utf-8") as f:
        json.dump(concepts, f, ensure_ascii=False, indent=2)

    top_concept = _select_top_concept(concepts)
    if not top_concept:
        logger.error("컨셉 top1 선택 실패")
        return concepts_path

    logger.info(f"Top1: {top_concept.get('concept_name')} (예상성공률 {top_concept.get('expected_success_rate')}%)")

    # ── 실제 유사 성공 사례 로드 ─────────────────────────────────────
    similar = _get_similar_projects(processed_dir, top_concept.get("goods_category", ""))
    logger.info(f"유사 성공 사례: {len(similar)}개")

    # ── Step 2+3+4: 기획서 + 등록 초안 + SNS 병렬 생성 ──────────────
    logger.info("Step2+3+4: 기획서 + 등록 초안 + SNS 카피 병렬 생성 중...")

    planning_md = None
    draft_md = None
    sns_content = None

    def _gen_planning():
        return call_claude(
            _build_planning_prompt(top_concept, similar, analysis),
            model=model, max_tokens=3000,
        )

    def _gen_draft():
        return call_claude(
            _build_draft_prompt(top_concept, similar),
            model=model, max_tokens=4000,
        )

    def _gen_sns():
        return call_claude(
            _build_sns_prompt(top_concept),
            model=model, max_tokens=1000,
        )

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(_gen_planning): "planning",
            executor.submit(_gen_draft): "draft",
            executor.submit(_gen_sns): "sns",
        }
        results = {}
        for future, label in [(f, futures[f]) for f in futures]:
            try:
                results[label] = future.result()
                logger.info(f"[{label}] 생성 완료 ({len(results[label] or '')}자)")
            except Exception as e:
                logger.error(f"[{label}] 생성 실패: {e}")
                results[label] = None

    planning_md = results.get("planning")
    draft_md = results.get("draft")
    sns_content = results.get("sns")

    # ── 기획서 저장 ───────────────────────────────────────────────────
    if planning_md:
        planning_path = os.path.join(output_dir, f"planning_{date_str}.md")
        with open(planning_path, "w", encoding="utf-8") as f:
            f.write(planning_md)
        logger.info(f"기획서 저장: {planning_path}")
    else:
        logger.error("기획서 생성 실패")

    # ── 등록 초안 저장 ────────────────────────────────────────────────
    if draft_md:
        draft_path = os.path.join(output_dir, f"launch_draft_{date_str}.md")
        with open(draft_path, "w", encoding="utf-8") as f:
            f.write(draft_md)
        logger.info(f"등록 초안 저장: {draft_path}")
    else:
        logger.error("등록 초안 생성 실패")

    # ── Step 5: GitHub Pages용 HTML 생성 (실제 수치 기반) ────────────
    logger.info("Step5: GitHub Pages HTML 생성 중...")
    os.makedirs(pages_dir, exist_ok=True)

    if planning_md and draft_md:
        html_content = _build_html_from_reports(top_concept, planning_md, draft_md, analysis, all_concepts=concepts)
        html_path = os.path.join(pages_dir, f"funding_page_{date_str}.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        logger.info(f"HTML 저장: {html_path} ({len(html_content)}자)")
    else:
        logger.warning("기획서 또는 초안 없음 — HTML 생성 스킵")

    # ── SNS 카피 저장 ─────────────────────────────────────────────────
    if sns_content:
        sns_data = _parse_json_response(sns_content, label="sns") or {"raw": sns_content}
        sns_path = os.path.join(pages_dir, f"sns_copy_{date_str}.json")
        with open(sns_path, "w", encoding="utf-8") as f:
            json.dump({"concept_name": top_concept.get("concept_name"), "date": date_str, "copy": sns_data},
                      f, ensure_ascii=False, indent=2)
        logger.info(f"SNS 카피 저장: {sns_path}")

    logger.info(f"launch_advisor 완료 → {concepts_path}")
    return concepts_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    from dotenv import load_dotenv
    load_dotenv(override=True)
    path = run_launch_advisor()
    print(f"결과: {path}")
