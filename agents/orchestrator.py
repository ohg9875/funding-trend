"""
Orchestrator Agent — 펀딩 트렌드 MVP
전체 파이프라인 조율:
  텀블벅 수집 ──┐
                ├─▶ 전처리 ─▶ 분석 ─┬─▶ reporter (병렬)
  와디즈 수집 ──┘                    └─▶ launch_advisor (병렬)

APScheduler로 매주 월요일 09:00 KST 자동 실행 지원
출력: data/raw/workflow_log_YYYYMMDD_HHMMSS.json
"""

import json
import logging
import os
import time
import yaml
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

logger = logging.getLogger(__name__)


def _load_config(config_path: str = "config.yaml") -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _run_with_retry(fn, label: str, max_retries: int = 3, **kwargs):
    """에이전트 실행 + 최대 3회 재시도"""
    for attempt in range(1, max_retries + 1):
        try:
            result = fn(**kwargs)
            return result
        except Exception as e:
            logger.warning(f"[{label}] 시도 {attempt}/{max_retries} 실패: {e}")
            if attempt < max_retries:
                time.sleep(3)
    logger.error(f"[{label}] {max_retries}회 재시도 모두 실패")
    return [] if "collector" in label.lower() else None


def run_pipeline(config_path: str = "config.yaml") -> dict:
    """
    전체 파이프라인 실행
    반환: workflow_log dict
    """
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    log = {
        "run_id": run_id,
        "status": "started",
        "tumblbug": {"count": 0, "enabled": True, "duration_sec": 0},
        "wadiz": {"count": 0, "duration_sec": 0},
        "warnings": [],
        "report_path": None,
        "advisor_path": None,
        "started_at": datetime.now().isoformat(),
        "finished_at": None,
    }

    cfg = _load_config(config_path)
    collect_cfg = cfg.get("collect", {})
    delay_min = float(collect_cfg.get("delay_min", 2))
    delay_max = float(collect_cfg.get("delay_max", 4))
    max_pages = int(collect_cfg.get("max_pages", 15))
    parallel = collect_cfg.get("parallel", True)

    raw_dir = "data/raw"
    processed_dir = "data/processed"
    reports_dir = "data/reports"

    # ── Step 1: 수집 (텀블벅 + 와디즈 병렬) ───────────────────────
    from agents.tumblbug_collector import (
        collect_tumblbug, _load_categories_from_config as tb_cats,
    )
    from agents.wadiz_collector import (
        collect_wadiz, _load_categories_from_config as wz_cats,
    )

    tumblbug_enabled = cfg.get("tumblbug", {}).get("enabled", True)
    log["tumblbug"]["enabled"] = tumblbug_enabled

    def _collect_tumblbug():
        if not tumblbug_enabled:
            logger.info("텀블벅 수집 비활성화 (config.yaml)")
            return []
        categories = tb_cats(config_path)
        return collect_tumblbug(
            categories=categories, max_pages=max_pages,
            output_dir=raw_dir, delay_min=delay_min, delay_max=delay_max,
        )

    def _collect_wadiz():
        categories = wz_cats(config_path)
        return collect_wadiz(
            category_codes=categories, max_pages=max_pages,
            output_dir=raw_dir, delay_min=delay_min, delay_max=delay_max,
        )

    logger.info(f"수집 시작 (parallel={parallel})")

    if parallel:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {
                executor.submit(_collect_tumblbug): "tumblbug",
                executor.submit(_collect_wadiz): "wadiz",
            }
            results = {}
            for future in as_completed(futures):
                label = futures[future]
                t0 = time.time()
                try:
                    results[label] = future.result() or []
                except Exception as e:
                    logger.warning(f"[{label}] 수집 실패: {e}")
                    log["warnings"].append(f"{label} 수집 실패: {e}")
                    results[label] = []
                log[label]["count"] = len(results[label])
                log[label]["duration_sec"] = round(time.time() - t0, 1)
    else:
        t0 = time.time()
        results = {"tumblbug": _collect_tumblbug() or []}
        log["tumblbug"].update({"count": len(results["tumblbug"]), "duration_sec": round(time.time() - t0, 1)})
        t0 = time.time()
        results["wadiz"] = _collect_wadiz() or []
        log["wadiz"].update({"count": len(results["wadiz"]), "duration_sec": round(time.time() - t0, 1)})

    # ── 양쪽 모두 0건이면 즉시 중단 ─────────────────────────────────
    if not results["tumblbug"] and not results["wadiz"]:
        msg = "텀블벅·와디즈 모두 0건 — 파이프라인 중단"
        logger.error(msg)
        log["status"] = "failed"
        log["warnings"].append(msg)
        log["finished_at"] = datetime.now().isoformat()
        _save_log(log, raw_dir)
        return log

    if not results["tumblbug"] and tumblbug_enabled:
        log["warnings"].append("텀블벅 0건 — 와디즈 단독 진행")
    if not results["wadiz"]:
        log["warnings"].append("와디즈 0건 — 텀블벅 단독 진행")

    # ── Step 2: 전처리 ────────────────────────────────────────────
    logger.info("전처리 시작")
    try:
        from agents.preprocessor import run_preprocessor
        unified = run_preprocessor(raw_dir=raw_dir, output_dir=processed_dir)
        log["unified_count"] = len(unified)
    except Exception as e:
        logger.error(f"전처리 실패: {e}")
        log["status"] = "failed"
        log["warnings"].append(f"전처리 실패: {e}")
        log["finished_at"] = datetime.now().isoformat()
        _save_log(log, raw_dir)
        return log

    # ── Step 3: 분석 ──────────────────────────────────────────────
    logger.info("분석 시작")
    try:
        from agents.analyzer import run_analyzer
        run_analyzer(processed_dir=processed_dir, output_dir=processed_dir)
    except Exception as e:
        logger.error(f"분석 실패: {e}")
        log["warnings"].append(f"분석 실패: {e}")

    # ── Step 4: 리포트 + launch_advisor (병렬) ─────────────────────
    logger.info("리포트 + launch_advisor 병렬 생성 시작")
    reporter_cfg = cfg.get("reporter", {})
    advisor_cfg = cfg.get("launch_advisor", {})

    def _run_reporter():
        from agents.reporter import run_reporter
        return run_reporter(
            processed_dir=processed_dir,
            output_dir=reports_dir,
            model=reporter_cfg.get("model", "claude-sonnet-4-20250514"),
            max_tokens=int(reporter_cfg.get("max_tokens", 2000)),
        )

    def _run_advisor():
        from agents.launch_advisor import run_launch_advisor
        return run_launch_advisor(
            processed_dir=processed_dir,
            output_dir=reports_dir,
            model=advisor_cfg.get("model", "claude-sonnet-4-20250514"),
            max_tokens=int(advisor_cfg.get("max_tokens", 4000)),
            concepts_count=int(advisor_cfg.get("concepts_count", 3)),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        f_reporter = executor.submit(_run_reporter)
        f_advisor = executor.submit(_run_advisor)

        for future, label in [(f_reporter, "reporter"), (f_advisor, "launch_advisor")]:
            try:
                result = future.result()
                if label == "reporter":
                    log["report_path"] = result
                else:
                    log["advisor_path"] = result
            except Exception as e:
                logger.error(f"[{label}] 실패: {e}")
                log["warnings"].append(f"{label} 실패: {e}")

    log["status"] = "success" if not log["warnings"] else "partial_success"
    log["finished_at"] = datetime.now().isoformat()
    _save_log(log, raw_dir)

    logger.info(
        f"파이프라인 완료 [{log['status']}] "
        f"리포트: {log.get('report_path')} / 어드바이저: {log.get('advisor_path')}"
    )

    # ── 슬랙 알림 (SLACK_WEBHOOK_URL 설정 시 자동 발송) ──────────────
    notify_cfg = cfg.get("notify", {})
    if notify_cfg.get("enabled", True):
        try:
            from utils.notifier import send_slack_notification
            webhook_env = notify_cfg.get("slack_webhook_url_env", "SLACK_WEBHOOK_URL")
            send_slack_notification(
                log,
                processed_dir=processed_dir,
                reports_dir=reports_dir,
                webhook_url=os.getenv(webhook_env, ""),
            )
        except Exception as e:
            logger.warning(f"슬랙 알림 오류: {e}")

    return log


def _save_log(log: dict, base_dir: str):
    os.makedirs(base_dir, exist_ok=True)
    log_path = os.path.join(base_dir, f"workflow_log_{log['run_id']}.json")
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)
    logger.info(f"워크플로우 로그 저장: {log_path}")


def schedule_weekly(config_path: str = "config.yaml"):
    """APScheduler로 매주 월요일 09:00 KST 자동 실행"""
    from apscheduler.schedulers.blocking import BlockingScheduler
    import pytz

    scheduler = BlockingScheduler(timezone=pytz.timezone("Asia/Seoul"))
    scheduler.add_job(
        lambda: run_pipeline(config_path),
        trigger="cron",
        day_of_week="mon",
        hour=9,
        minute=0,
    )
    logger.info("스케줄러 시작 — 매주 월요일 09:00 KST")
    scheduler.start()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
    )
    from dotenv import load_dotenv
    load_dotenv()
    result = run_pipeline()
    print(f"\n=== 펀딩 트렌드 파이프라인 결과 ===")
    print(f"상태: {result['status']}")
    print(f"텀블벅: {result['tumblbug']['count']}개")
    print(f"와디즈: {result['wadiz']['count']}개")
    if result.get("report_path"):
        print(f"리포트: {result['report_path']}")
    if result.get("advisor_path"):
        print(f"어드바이저: {result['advisor_path']}")
    if result.get("warnings"):
        print(f"경고: {result['warnings']}")
