"""콘솔 출력 방어.

이 환경의 콘솔 인코딩은 **cp949** 이고 한국어 코드페이지에는 em-dash(U+2014)와
`⚠️`(U+26A0) 가 없다. `print` 한 줄이 UnicodeEncodeError 로 죽으면 그 줄뿐 아니라
**뒤따르는 출력이 전부** 사라진다.

세 진입점이 전부 "다 만든 뒤에 찍는" 모양이라 피해가 크다:
  - `main.py`      : 그래프를 다 돌린 뒤 출력 → 분석 결과 100% 유실
  - `load_internal`: os.replace 로 DB 를 교체한 뒤 출력 → DB 는 바뀌었는데 경고만 사라짐
  - `generate_dummy`: DB·임베딩을 다 쓴 뒤 출력 → 산출물은 남고 리포트만 사라짐

**리터럴 청소로는 못 막는다.** 찍는 내용이 6개 모듈에서 흘러들어오고(LLM 산출물·DB
경로·wafer_id) 앞으로도 늘어난다. 그래서 출력 **지점**에서 막는다.

`sys.stdout.reconfigure(errors="replace")` 는 쓰지 않는다 — 프로세스 전역 상태를 바꿔
이 코드를 라이브러리로 부르는 쪽의 출력 동작까지 조용히 바꾼다.
"""

import sys


def say(line: str = "") -> None:
    """print 하되, 콘솔이 못 싣는 글자는 '?' 로 바꿔서라도 줄을 남긴다."""
    try:
        print(line)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(line.encode(enc, "replace").decode(enc, "replace"))
