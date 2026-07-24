"""프로토타입 설정. 데이터 경로 + 외부 연동(EDS/LLM) 모드 토글.

핵심: EDS·LLM 은 mode 로 데모(local/mock) ↔ 운영(http/사내) 구현을 바꿔 끼운다.
  - 정확한건 사내 코드가 정확. 여기는 이런식이다라고만
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "yield.db"
EMB_DIR = BASE_DIR / "data" / "embeddings"

# 수율 "이상" 판정 임계 (문서 9절: 절대값 방식)
YIELD_THRESHOLD = 90.0

# EDS 유사맵 도구: "local" = 로컬 hnswlib, "http" = 사내 Flask /search
EDS_MODE = "local"
EDS_MIN_SIMILARITY = 0.5  # 이 미만 후보는 제외 (무관 wafer 컷). 그룹~0.92 / 외부~0.10
EDS_HTTP_URL = "https://<사내-eds-호스트>/search"  # 운영 시 교체
EDS_HTTP_VERIFY = False  # 사내 자체 인증서 → 프로토타입은 우회, 운영은 .pem 경로로 전환

# LLM: "mock" = 규칙 기반(사내망 밖 데모), "openai" = 사내 OpenAI 호환 서빙
LLM_MODE = os.getenv("LLM_MODE", "mock")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://<사내-llm-호스트>/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "dummy")
LLM_MODEL = os.getenv("LLM_MODEL", "<사내-모델명>")

# 분석 루프 통제 (analysis_loop_design.md 부품 4b)
MAX_LOOPS = 6              # 가드레일: 최대 순환 횟수 (무한루프 차단)
CONFIDENCE_THRESHOLD = 0.8 # finalize 승인 임계 확신도

# commonality 후보의 '판별 통과(passes)' 기준 — 게이트 증거로 쓸 최소 신뢰선.
# 후보≠결론 철학상 못 박지 않고 실데이터 보며 조정한다.
COMMONALITY_PASS_MIN_SCORE = float(os.getenv("COMMONALITY_PASS_MIN_SCORE", "0.5"))
COMMONALITY_PASS_MIN_TARGET = int(os.getenv("COMMONALITY_PASS_MIN_TARGET", "2"))

# 형제 묶기 (status 입력 재설계): "같은 사건" 판정이라 유사 사례 검색(0.5)보다 높게.
# 실행 중 불변이므로 결정론 원칙과 충돌 없음 (재설계 문서 6절 2번).
SIBLING_MIN_SIMILARITY = float(os.getenv("SIBLING_MIN_SIMILARITY", "0.8"))
SIBLING_SEARCH_K = 50          # 형제 후보 조회 폭 (인덱스 크기 미만이면 됨)
# 대조군 "부족" 판정 최소 크기 (재설계 문서 7절 — 미만이면 확장 대신 정직 보고)
CONTROL_MIN_SIZE = int(os.getenv("CONTROL_MIN_SIZE", "3"))
