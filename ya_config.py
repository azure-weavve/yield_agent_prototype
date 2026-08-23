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
EDS_MODE = os.getenv("EDS_MODE", "local")
EDS_MIN_SIMILARITY = 0.5  # 이 미만 후보는 제외 (무관 wafer 컷). 그룹~0.92 / 외부~0.10
EDS_HTTP_URL = os.getenv("EDS_URL")  # 운영 시 교체
# 사내 자체 인증서 → 프로토타입은 우회, 운영은 .pem 경로로 전환.
# .env 에 경로를 주면 그 경로로 검증한다("EDS_HTTP_VERIFY=/etc/ssl/사내루트.pem").
# ⚠️ **기본값은 여전히 우회(False)다.** 이걸 '켜짐'으로 뒤집는 것은 별건이다
#    (deferred-internal-integration.md 4번) — 여기서는 경로 지정 통로만 열었다.
EDS_HTTP_VERIFY = os.getenv("EDS_HTTP_VERIFY") or False

# LLM: "mock" = 규칙 기반(사내망 밖 데모), "openai" = 사내 OpenAI 호환 서빙
LLM_MODE = os.getenv("LLM_MODE", "mock")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://<사내-llm-호스트>/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "dummy")
LLM_MODEL = os.getenv("LLM_MODEL", "<사내-모델명>")
# 사내 게이트웨이가 User-Id 헤더로 요구하는 AD ID. 기본값을 두지 않는다 —
# 아무 값이나 넣으면 남의 ID 로 호출한 기록이 남고, 빈 값이면 헤더가 조용히 비어
# 나간다. openai 모드로 들어갈 때 llm/client.py 가 비었는지 먼저 확인한다.
USER_NAME = os.getenv("USER_NAME")
# 응답이 안 오면 언젠가는 포기해야 한다. 이 값이 없으면 사내 서빙이 멈췄을 때 예외가
# 영영 안 나고 프로세스가 매달린다 - graph/nodes.py 의 LLM 실패 방어가 탈 경로 자체가
# 사라진다. 실측 후 조정 (사내 모델 응답 시간을 아직 모른다).
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "60"))
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "2"))

# 분석 루프 통제 (analysis_loop_design.md 부품 4b)
# 가드레일: 최대 순환 횟수 (무한루프 차단).
# **등록 가설 수에 매여 있다.** 게이트는 등록 가설을 전부 돌린 뒤에만 no_signal 을
# 선언하므로, 최소한 (가설 수 + 첫 finalize 시도 + 마지막 finalize) 만큼은 있어야
# 한다. 모자라면 no_signal 케이스가 루프 소진(inconclusive)으로 끝나 사유가 틀린
# 보고가 된다. 가설 4개인 지금은 6 이 딱 맞아떨어져 여유가 없어서 7 로 둔다.
# tests/test_state.py 가 이 관계를 단언으로 지킨다 (마진 +3 - 왜 +2 로는 모자란지도
# 거기 적혀 있다). **가설을 5개로 늘리면 그 테스트가 걸린다. 숫자를 올리기 전에
# 게이트의 "전부 돌린 뒤에만 no_signal" 규칙부터 다시 볼 것** - 지금 metro 축은
# 계측 짝이 없어 상시 빈손인데도 그 규칙 때문에 반드시 한 바퀴를 먹는다.
MAX_LOOPS = 7
CONFIDENCE_THRESHOLD = 0.8 # finalize 승인 임계 확신도

# commonality 는 **두 종류의 임계**를 쓴다. 이름이 비슷해 헷갈리므로 구분해 둔다.
#
#  (1) 탐색 범위 (COMMONALITY_*)      — 도구가 후보를 어디까지 낼 것인가.
#      tools/commonality.py 가 읽는다. 여기서 잘린 후보는 LLM 도 게이트도 못 본다.
#  (2) 판별선  (COMMONALITY_PASS_*)   — 게이트가 증거로 쓸 최소 신뢰선.
#      domain/engine.py 가 읽어 후보의 passes 를 정한다. 미통과 후보도 목록에는 남는다.
#
# 둘 다 후보≠결론 철학상 못 박지 않고 실데이터 보며 조정한다.
COMMONALITY_MIN_TARGET = int(os.getenv("COMMONALITY_MIN_TARGET", "2"))
COMMONALITY_TOP_K = int(os.getenv("COMMONALITY_TOP_K", "20"))
COMMONALITY_MIN_SCORE = float(os.getenv("COMMONALITY_MIN_SCORE", "0.0"))
COMMONALITY_PASS_MIN_SCORE = float(os.getenv("COMMONALITY_PASS_MIN_SCORE", "0.5"))
COMMONALITY_PASS_MIN_TARGET = int(os.getenv("COMMONALITY_PASS_MIN_TARGET", "2"))
COMMONALITY_PERMUTATIONS = int(os.getenv("COMMONALITY_PERMUTATIONS", "1000"))

# 센서(2단): "local" = yield.db 의 sensor_log, "http" = 사내 FDC, "off" = 미연결
# "off" 는 도구를 아예 **등록하지 않는다**(tools/agent_tools.py). FDC 배선 전에
# 투입하면 LLM 이 2단을 부르고 매번 실패해 루프만 태우는데, 실패 메시지는
# "근거를 더 좁혀라" 로 읽혀 같은 호출을 반복하기까지 한다.
SENSOR_MODE = os.getenv("SENSOR_MODE", "local")
SENSOR_HTTP_URL = os.getenv("SENSOR_HTTP_URL", "https://<사내-fdc-호스트>/sensor")
# 2단 반환 절단 — fetch 량과 무관하게 유계로 만든다 (후보≠결론)
SENSOR_TOP_K = int(os.getenv("SENSOR_TOP_K", "10"))
# 한 그룹의 센서 표본이 이 미만이면 비교하지 않는다 (표본 2장짜리 효과크기는 허상)
SENSOR_MIN_SAMPLE = int(os.getenv("SENSOR_MIN_SAMPLE", "3"))

# 형제 묶기 (status 입력 재설계): "같은 사건" 판정이라 유사 사례 검색(0.5)보다 높게.
# 실행 중 불변이므로 결정론 원칙과 충돌 없음 (재설계 문서 6절 2번).
SIBLING_MIN_SIMILARITY = float(os.getenv("SIBLING_MIN_SIMILARITY", "0.8"))
SIBLING_SEARCH_K = 50          # 형제 후보 조회 폭 (인덱스 크기 미만이면 됨)
# 대조군 "부족" 판정 최소 크기 (재설계 문서 7절 — 미만이면 확장 대신 정직 보고)
CONTROL_MIN_SIZE = int(os.getenv("CONTROL_MIN_SIZE", "3"))
