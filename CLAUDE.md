# 펀딩 트렌드 인사이트 & 상품 기획 자동화 MVP

## 프로젝트 개요
텀블벅·와디즈 크라우드펀딩 데이터로 트렌드를 분석하고,
"지금 만들면 잘 팔릴 상품" 컨셉과 펀딩 상세 페이지를 자동 생성하는 AI 파이프라인.

## 실행 방법
```bash
# 최초 1회 설정
pip install -r requirements.txt
playwright install chromium
cp .env.example .env   # ANTHROPIC_API_KEY 입력

# 전체 파이프라인
python scripts/run_pipeline.py

# 수집만 테스트
python scripts/run_collector_only.py

# launch_advisor만 단독 실행 (기존 trend_analysis 파일 필요)
python scripts/run_advisor_only.py
```

## 테스트 실행 (Windows UTF-8)
```bash
PYTHONIOENCODING=utf-8 python tests/test_analyzer.py
PYTHONIOENCODING=utf-8 python tests/test_launch_advisor.py
```

## 디렉토리 규칙
- `data/raw/`       — 크롤링 원본 (tumblbug_YYYYMMDD.json, wadiz_YYYYMMDD.json)
- `data/processed/` — 전처리·분석 결과 (unified_YYYYMMDD.json, trend_analysis_YYYYMMDD.json)
- `data/reports/`   — 주간 리포트 + 상품 컨셉 JSON
- `data/pages/`     — 생성된 펀딩 페이지 HTML + SNS 카피

## 에이전트 실행 순서
```
tumblbug_collector ──┐
                      ├─▶ preprocessor ─▶ analyzer ─┬─▶ reporter
wadiz_collector    ──┘                               └─▶ launch_advisor
                                                           ├─ Step1: concepts JSON
                                                           ├─ Step2+3(병렬): HTML + SNS 카피
```

## 코딩 규칙
- 모든 에이전트는 단독 실행(`if __name__ == "__main__":`) 가능하게 작성
- 크롤링 딜레이: 2~4초 랜덤 (config.yaml delay_min/max)
- 에러 시 로그 출력 후 스킵 — 단, 양쪽 수집기 모두 0건이면 즉시 중단
- 파일명에 날짜 포함 (YYYYMMDD 포맷)
- Claude API 호출은 utils/claude_client.py 공통 헬퍼 사용 (직접 호출 금지)
- 크롤링된 텍스트는 preprocessor에서 html.escape() 처리 필수

## 환경변수 (.env)
- `ANTHROPIC_API_KEY` — reporter + launch_advisor 전용
- `.env`는 절대 git 커밋 금지 (.gitignore 포함)

## Wadiz 크롤링 방식
HTML 스크래핑 X. Playwright 세션 수립 후 내부 JSON API 직접 호출:
- POST `https://service.wadiz.kr/api/search/v2/funding`
- `--disable-blink-features=AutomationControlled` + 한국어 locale

## 디자인 규칙 (HTML 출력)
- 라이트 모드 통일 (--bg: #ffffff)
- 폰트: Pretendard Variable (CDN)
- 펀딩 페이지: mobile-first, 320/768/1200px 브레이크포인트
- AI Slop 금지: 보라 그라디언트 히어로, 맥락없는 3열 아이콘 카드 금지
- CTA 버튼 최소 44×44px 터치 타깃
