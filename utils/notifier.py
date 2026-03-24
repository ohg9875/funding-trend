"""
Slack Incoming Webhook 알림 유틸리티
파이프라인 완료 후 트렌드 요약을 슬랙 채널로 발송

설정:
  .env: SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
  config.yaml:
    notify:
      enabled: true
      slack_webhook_url_env: SLACK_WEBHOOK_URL  # 환경변수 이름
"""

import json
import logging
import os
from glob import glob
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_DIRECTION_SYMBOL = {"up": "↑", "down": "↓", "flat": "→"}


def _load_latest_analysis(processed_dir: str = "data/processed") -> Optional[dict]:
    files = sorted(glob(f"{processed_dir}/trend_analysis_*.json"), reverse=True)
    if not files:
        return None
    with open(files[0], encoding="utf-8") as f:
        return json.load(f)


def _load_latest_concepts(reports_dir: str = "data/reports") -> Optional[list]:
    files = sorted(glob(f"{reports_dir}/concepts_*.json"), reverse=True)
    if not files:
        return None
    with open(files[0], encoding="utf-8") as f:
        return json.load(f)


def _build_message(log: dict, analysis: Optional[dict], concepts: Optional[list]) -> str:
    status = log.get("status", "unknown")
    status_icon = "✅" if status == "success" else ("⚠️" if status == "partial_success" else "❌")
    date_str = log.get("run_id", "")[:8]
    if date_str:
        date_str = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"

    tb_count = log.get("tumblbug", {}).get("count", 0)
    wz_count = log.get("wadiz", {}).get("count", 0)
    total = tb_count + wz_count

    lines = [
        f"{status_icon} *펀딩 트렌드 리포트 완료* ({date_str})",
        f"텀블벅 {tb_count:,}개 + 와디즈 {wz_count:,}개 = *{total:,}개* 분석",
        "",
    ]

    # HOT 카테고리 TOP 3
    if analysis:
        by_cat = analysis.get("by_goods_category", {})
        wow = analysis.get("week_over_week", {})
        top_cats = sorted(by_cat.items(), key=lambda x: x[1].get("avg_trend_score", 0), reverse=True)[:3]

        if top_cats:
            lines.append("🔥 *이번 주 HOT 카테고리*")
            for i, (cat, data) in enumerate(top_cats, 1):
                score = data.get("avg_trend_score", 0)
                delta_info = ""
                if cat in wow:
                    delta = wow[cat]["delta"]
                    sym = _DIRECTION_SYMBOL.get(wow[cat]["direction"], "")
                    delta_info = f"  {sym}{delta:+.1f}" if delta != 0 else f"  {sym}"
                lines.append(f"  {i}. {cat}  {score}점{delta_info}")
            lines.append("")

    # TOP 추천 컨셉
    if concepts:
        top = max(concepts, key=lambda c: c.get("expected_success_rate", 0))
        name = top.get("concept_name", "")
        rate = top.get("expected_success_rate", 0)
        price = top.get("price_range", "")
        lines.append(f"💡 *TOP 추천 컨셉*")
        lines.append(f"  {name} — 예상 성공률 {rate}%")
        if price:
            lines.append(f"  가격대: {price}")
        lines.append("")

    # 경고
    warnings = log.get("warnings", [])
    if warnings:
        lines.append("⚠️ *경고*")
        for w in warnings[:3]:
            lines.append(f"  • {w}")

    return "\n".join(lines)


def send_slack_notification(
    log: dict,
    processed_dir: str = "data/processed",
    reports_dir: str = "data/reports",
    webhook_url: Optional[str] = None,
) -> bool:
    """
    슬랙 Incoming Webhook으로 파이프라인 결과 발송

    반환: True(성공) / False(실패 또는 비활성)
    """
    url = webhook_url or os.getenv("SLACK_WEBHOOK_URL", "")
    if not url:
        logger.debug("SLACK_WEBHOOK_URL 미설정 — 슬랙 알림 건너뜀")
        return False

    analysis = _load_latest_analysis(processed_dir)
    concepts = _load_latest_concepts(reports_dir)

    message = _build_message(log, analysis, concepts)

    try:
        resp = requests.post(url, json={"text": message}, timeout=10)
        if resp.status_code == 200:
            logger.info("슬랙 알림 발송 완료")
            return True
        else:
            logger.warning(f"슬랙 알림 실패: HTTP {resp.status_code} — {resp.text[:100]}")
            return False
    except requests.RequestException as e:
        logger.warning(f"슬랙 알림 네트워크 오류: {e}")
        return False
