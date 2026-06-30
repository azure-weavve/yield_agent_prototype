"""프로토타입 설정. 데이터 경로 + 외부 연동(EDS/LLM) 모드 토글.

핵심: EDS·LLM 은 mode 로 데모(local/mock) ↔ 운영(http/사내) 구현을 바꿔 끼운다.
"""

from pathlib import Path

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
LLM_MODE = "mock"
LLM_BASE_URL = "https://<사내-llm-호스트>/v1"  # 운영 시 교체
LLM_API_KEY = "dummy"  # 사내 서빙이 키 불요면 임의값
LLM_MODEL = "<사내-모델명>"
