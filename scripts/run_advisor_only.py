"""launch_advisor만 단독 실행 (기존 trend_analysis 파일 필요)"""
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(override=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

import yaml

if __name__ == "__main__":
    cfg = {}
    try:
        with open("config.yaml", "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
    except Exception:
        pass

    advisor_cfg = cfg.get("launch_advisor", {})

    import webbrowser
    import glob as _glob

    from agents.launch_advisor import run_launch_advisor
    path = run_launch_advisor(
        model=advisor_cfg.get("model", "claude-sonnet-4-20250514"),
        max_tokens=int(advisor_cfg.get("max_tokens", 4000)),
        concepts_count=int(advisor_cfg.get("concepts_count", 3)),
    )
    print(f"결과: {path}")

    # 생성된 최신 HTML을 브라우저로 자동 오픈
    html_files = sorted(_glob.glob("data/pages/funding_page_*.html"), reverse=True)
    if html_files:
        html_path = os.path.abspath(html_files[0])
        print(f"\n🌐 펀딩 페이지 미리보기: {html_path}")
        webbrowser.open(f"file:///{html_path}")
