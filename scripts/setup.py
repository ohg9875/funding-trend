"""최초 1회 환경 초기화"""
import os
import subprocess
import sys


def main():
    print("=== 펀딩 트렌드 MVP 환경 초기화 ===\n")

    # 디렉토리 생성
    for d in ["data/raw", "data/processed", "data/reports", "data/pages"]:
        os.makedirs(d, exist_ok=True)
        print(f"  디렉토리 생성: {d}")

    # .env 확인
    if not os.path.exists(".env"):
        import shutil
        shutil.copy(".env.example", ".env")
        print("\n  .env 파일 생성됨 — ANTHROPIC_API_KEY를 입력해주세요")
    else:
        print("\n  .env 파일 확인됨")

    # Playwright 브라우저 설치
    print("\nPlaywright Chromium 설치 중...")
    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)

    print("\n=== 초기화 완료 ===")
    print("실행: python scripts/run_collector_only.py  (크롤러 테스트)")
    print("실행: python scripts/run_pipeline.py        (전체 파이프라인)")
    print("실행: python scripts/run_advisor_only.py    (launch_advisor 단독)")


if __name__ == "__main__":
    main()
