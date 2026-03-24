"""
공통 Claude API 헬퍼
reporter.py, launch_advisor.py에서 직접 anthropic 호출 대신 이 모듈 사용.

재시도 로직:
  1회 실패 → 30초 대기 → 재시도
  2회 실패 → 60초 대기 → 재시도
  3회 모두 실패 → None 반환

호출 상태 머신:
  call_claude()
       │
       ▼
   [API 호출]──성공──▶ 빈 응답 검사 ──정상──▶ text 반환
       │                    │
       │ 실패               │ 빈 응답
       ▼                    ▼
  [retry < max]         ValueError → 재시도
       │ yes
       ▼
  [backoff 대기]
       │
       ▼
   [재시도]
       │ max 초과
       ▼
     None 반환
"""

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

_RETRY_DELAYS = [30, 60]  # 1차 실패 후 30초, 2차 실패 후 60초


def call_claude(
    prompt: str,
    model: str = "claude-sonnet-4-6",
    max_tokens: int = 2000,
    max_retries: int = 3,
) -> Optional[str]:
    """
    Claude API 단일 호출 (재시도 + 빈 응답 검증 포함)

    반환:
      str  — 정상 응답 텍스트
      None — max_retries 초과 또는 AuthenticationError
    """
    import anthropic

    client = anthropic.Anthropic()

    for attempt in range(1, max_retries + 1):
        try:
            message = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )

            # 빈 응답 검증 (CRITICAL GAP 방어)
            if not message.content or not message.content[0].text.strip():
                raise ValueError("Claude 빈 응답 반환")

            return message.content[0].text

        except anthropic.AuthenticationError:
            logger.error("ANTHROPIC_API_KEY가 유효하지 않습니다 — 재시도 중단")
            return None

        except anthropic.RateLimitError:
            delay = _RETRY_DELAYS[min(attempt - 1, len(_RETRY_DELAYS) - 1)]
            logger.warning(f"Claude RateLimitError — {delay}초 대기 후 재시도 ({attempt}/{max_retries})")
            if attempt < max_retries:
                time.sleep(delay)

        except Exception as e:
            delay = _RETRY_DELAYS[min(attempt - 1, len(_RETRY_DELAYS) - 1)]
            logger.warning(f"Claude API 오류 ({attempt}/{max_retries}): {e}")
            if attempt < max_retries:
                time.sleep(delay)

    logger.error(f"Claude API {max_retries}회 모두 실패")
    return None
