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
wadiz_collector    ──┘           │                   └─▶ launch_advisor
                          (unified_*.json)                  ├─ Step1: concepts JSON
                                 │                          ├─ Step2+3+4 (3-worker 병렬):
                                 └──────────────────────────┤   기획서 MD + 등록 초안 MD + SNS JSON
                                                            └─ Step5: GitHub Pages HTML
                                                                 (비교 표 + Slack 공유 버튼)
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

### 기반 설정
- 라이트 모드 통일 (배경: #ffffff)
- 폰트: Pretendard Variable (CDN: jsdelivr orioncactus pretendardvariable.css)
- Mobile-first, 브레이크포인트: 320px / 768px / 1200px

### 색상 시스템 (Claude가 임의 선택 금지 — 아래 토큰 사용)
```
--color-primary:   #FF5A1F   /* 주 CTA, 강조 (따뜻한 오렌지-레드) */
--color-primary-hover: #E04A10
--color-surface:   #F7F8FA   /* 섹션 배경 교차 */
--color-border:    #E2E8F0
--color-text:      #1A202C   /* 본문 */
--color-text-sub:  #4A5568   /* 보조 텍스트 */
--color-text-muted:#718096   /* 메타 텍스트 — 최소 4.5:1 대비비 보장 */
--color-success:   #38A169
--color-progress:  #FF5A1F   /* 달성률 바 */
```

### 타입 스케일 (Major Third 1.25 기반)
```
--text-xs:   0.75rem   /* 뱃지, 메타 */
--text-sm:   0.875rem  /* 보조 설명 */
--text-base: 1rem      /* 본문 */
--text-lg:   1.25rem   /* 소제목 */
--text-xl:   1.563rem  /* 섹션 타이틀 */
--text-2xl:  1.953rem  /* 히어로 서브타이틀 */
--text-3xl:  2.441rem  /* 히어로 메인 타이틀 */
```
- 본문 line-height: 1.7 (가독성)
- 제목 line-height: 1.2
- word-break: keep-all (한국어 단어 분리 방지)

### 크라우드펀딩 필수 섹션 구성
히어로 → **펀딩 현황 위젯** → 상품 소개 → 리워드 구성 → 제작자 소개 → FAQ → 하단 고정 CTA

**펀딩 현황 위젯 (히어로 직하단 — 필수):**
- 달성률 숫자 + 진행 바 (CSS width: {rate}%)
- 후원자 수 (명)
- 남은 기간 (D-day 또는 "곧 마감")
- 목표 금액 달성 여부 메시지

**하단 고정 CTA 바 (position: sticky; bottom: 0):**
- 모바일에서 항상 노출
- 상품명 + 최저가 + "지금 후원하기" 버튼
- z-index: 100, backdrop: white + shadow

### 인터랙션 상태 (HTML 프롬프트에 반드시 포함)
- 리워드 카드: 기본 / hover / 품절(sold-out: opacity 0.5 + "마감" 오버레이) / 인기(POPULAR 뱃지)
- CTA 버튼: 기본 / hover / active (transform scale 0.98)
- FAQ 아코디언: 접힘 / 펼침 (CSS transition 0.2s)

### 신뢰 요소 (Trust Signals — 필수 포함)
- "펀딩 미달성 시 전액 환불" 문구 (히어로 또는 CTA 근처)
- "결제는 펀딩 성공 후 진행" 안내
- 제작자 이름/브랜드 + 이전 프로젝트 이력 (1줄 이상)
- 교환/환불 정책 FAQ 항목 1개 이상

### 이미지 플레이스홀더 규칙
- 점선 테두리(dashed border) placeholder 금지
- 실선 테두리 + 배경색 + 상품 관련 이모지 + "이미지 준비 중" 텍스트 조합 사용
- 배경: var(--color-surface), 테두리: 1px solid var(--color-border)

### 카피 톤 앤 보이스
- 존댓말 (~입니다, ~해요체) 통일
- CTA 문구: "지금 후원하기" (현재 후원하기 X, 구매하기 X)
- 에러/안내: "잠시 후 다시 시도해 주세요" (기계적 영어 번역투 금지)
- 섹션 제목: 명사형 종결 ("리워드 구성", "제작자 소개") 또는 짧은 동사형 ("왜 이 상품인가")

### 반응형 리플로우 규칙
- 320px: 단일 컬럼, 히어로 타이틀 text-xl (1.563rem), 패딩 16px
- 768px~: 2컬럼 가능, 히어로 타이틀 text-2xl, 패딩 24px
- 1200px~: 히어로 좌(텍스트)+우(이미지) 분리, 최대폭 1200px 고정
- 펀딩 현황 위젯: 320px에서 2×2 그리드, 768px~에서 4열 1행

### AI Slop 금지 패턴
- 보라/인디고 그라디언트 히어로 배경 금지
- 맥락 없는 3열 이모지 아이콘 카드 금지
- Creator avatar: 이모지+그라디언트 원형 금지 — 이니셜 or 실사 스타일 아바타
- 모든 섹션 동일 박스 그림자(0 4px 20px rgba) 반복 금지 — 위계에 따라 차별화

### 접근성 기준
- CTA 버튼: 최소 44×44px 터치 타깃
- 색상 대비: 본문 텍스트 최소 4.5:1 (WCAG AA), 대형 텍스트 3:1
- 포커스 링: `outline: 2px solid var(--color-primary); outline-offset: 2px` (outline: none 금지)
- 이미지 대체텍스트: `alt` 속성 필수 (장식용은 `alt=""`)
- `<html lang="ko">` 필수
