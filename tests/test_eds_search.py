"""HttpEDSSearcher 가 사내 응답 계약(similar_wafers 매핑·None 제외·top-k)을 지키는지.

사내 /search 응답은 self 를 query_wafer 로 분리하므로 similar_wafers 엔 자기 자신이 없고,
similarity 는 음수 스케일이라 절대 임계(EDS_MIN_SIMILARITY) 필터를 적용하지 않는다
(f13b591 "도메인지식 주입 준비" 참조 — 서버 rank 순 + top-k 로만 컷).
LocalEDSSearcher 는 hnswlib 인덱스 생성물이 필요하므로 여기서는 다루지 않는다 (E2E 가 커버).
"""

import requests

from tools import agent_tools, eds_search, grouping
from tools.eds_search import HttpEDSSearcher


class _FakeResp:
    def __init__(self, similar_wafers):
        self._similar = similar_wafers

    def raise_for_status(self):
        pass

    def json(self):
        return {"query_wafer": {"wafer_id": "W1"}, "similar_wafers": self._similar}


def _patch_post(monkeypatch, similar_wafers):
    monkeypatch.setattr(requests, "post", lambda *a, **kw: _FakeResp(similar_wafers))


def test_http_search_maps_similar_wafers_and_skips_none(monkeypatch):
    _patch_post(monkeypatch, [
        {"rank": 1, "wafer_id": "W2", "similarity": -0.18},
        {"rank": 2, "wafer_id": "W3", "similarity": None},   # similarity 없음 → 제외
        {"rank": 3, "wafer_id": None, "similarity": -0.21},  # wafer_id 없음 → 제외
        {"rank": 4, "wafer_id": "W5", "similarity": -0.23},
    ])
    out = HttpEDSSearcher().search("W1", k=5)
    assert [r["wafer_id"] for r in out] == ["W2", "W5"]   # 서버 rank 순 보존, None 항목만 탈락
    assert out[0]["similarity"] == -0.18                  # 음수 스케일 그대로 (절대 임계 필터 없음)


def test_http_search_truncates_to_k(monkeypatch):
    _patch_post(monkeypatch, [
        {"rank": i, "wafer_id": f"W{i}", "similarity": -0.1 - i * 0.01} for i in range(2, 8)
    ])
    out = HttpEDSSearcher().search("W1", k=3)
    assert len(out) == 3
    assert [r["wafer_id"] for r in out] == ["W2", "W3", "W4"]


def test_both_call_paths_share_one_searcher(monkeypatch):
    """두 호출 경로가 인덱스를 한 번만 로드한다 (미룸 10번).

    예전에는 `grouping` 과 `agent_tools` 가 각자 lazy singleton 을 들고 있어 같은
    hnswlib 인덱스가 두 번 올라갔다(메모리·기동시간 낭비).

    이 테스트가 잡는 것은 **`eds_search` 의 공유 캐시가 사라지는 것**이다. 변이로 확인:
    캐시를 없애면 build 가 2회 불려 죽는다. 반대로 호출부가 자기 캐시를 **되살리는**
    변이는 이 테스트로 못 잡는다 — 공유 캐시가 살아 있는 한 로드는 여전히 1회라
    낭비가 생기지 않기 때문이다(그 경우는 중복 코드지 이중 로드가 아니다).
    """
    class _Stub:
        def search(self, wafer_id, k):
            return []

    builds = []
    monkeypatch.setattr(eds_search, "_searcher", None)      # 캐시 비우고 시작
    monkeypatch.setattr(eds_search, "_build_searcher",
                        lambda: (builds.append(1), _Stub())[1])

    grouping.normalize_target(["W2406_02"])                 # 경로 1
    agent_tools.search_similar.invoke({"wafer_id": "W2406_02", "k": 2})   # 경로 2

    assert builds == [1]


def test_eds_mode_is_switchable_by_env():
    """`EDS_MODE` 를 .env 로 바꿀 수 있어야 한다 (점검표 7장 a번).

    상수로 박혀 있으면 사내 EDS 를 쓰려고 **코드를 고쳐야** 하고, 점검표 0-2 가
    "EDS_MODE 는 .env 로 안 바뀐다" 라는 예외 안내를 계속 들고 있어야 한다.
    다른 모드 토글(LLM_MODE·SENSOR_MODE)은 이미 env 를 읽는데 이것만 빠져 있었다.

    별도 프로세스로 확인하는 이유: `ya_config` 는 import 시점에 env 를 읽으므로
    이미 import 된 이 세션에서는 값을 바꿔도 반영되지 않는다.
    """
    import os
    import subprocess
    import sys

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    proc = subprocess.run(
        [sys.executable, "-c",
         "import ya_config, tools.eds_search as e; "
         "print(ya_config.EDS_MODE, type(e._build_searcher()).__name__)"],
        capture_output=True, cwd=root, env={**os.environ, "EDS_MODE": "http"})

    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert proc.stdout.decode().split() == ["http", "HttpEDSSearcher"]
