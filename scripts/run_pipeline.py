"""전체 파이프라인 실행"""
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("pipeline.log", encoding="utf-8"),
    ]
)

from agents.orchestrator import run_pipeline

if __name__ == "__main__":
    import webbrowser
    import glob as _glob

    result = run_pipeline()
    print(f"\n=== 파이프라인 결과 ===")
    print(f"상태: {result['status']}")
    print(f"텀블벅: {result['tumblbug']['count']}개")
    print(f"와디즈: {result['wadiz']['count']}개")
    if result.get("report_path"):
        print(f"리포트: {result['report_path']}")
    if result.get("advisor_path"):
        print(f"어드바이저: {result['advisor_path']}")
    if result.get("warnings"):
        print(f"경고: {result['warnings']}")

    # 생성된 최신 HTML을 브라우저로 자동 오픈
    html_files = sorted(_glob.glob("data/pages/funding_page_*.html"), reverse=True)
    if html_files:
        html_path = os.path.abspath(html_files[0])
        print(f"\n🌐 펀딩 페이지 미리보기: {html_path}")
        webbrowser.open(f"file:///{html_path}")
