"""HttpEDSSearcher 가 인터페이스 계약(자기 자신 제외, 최소 유사도 필터)을 지키는지.

LocalEDSSearcher 는 hnswlib 인덱스 생성물이 필요하므로 여기서는 다루지 않고
(E2E 가 커버), 사내 전환 시 달라질 수 있는 HTTP 구현만 가짜 응답으로 검증한다.
"""

import requests

import config
from tools.eds_search import HttpEDSSearcher


class _FakeResp:
    def __init__(self, results):
        self._results = results

    def raise_for_status(self):
        pass

    def json(self):
        return {"results": self._results}


def _patch_post(monkeypatch, results):
    monkeypatch.setattr(requests, "post", lambda *a, **kw: _FakeResp(results))


def test_http_search_excludes_self_low_similarity_and_none_score(monkeypatch):
    _patch_post(monkeypatch, [
        {"wafer_id": "W1", "score": 1.0},    # 자기 자신 → 제외
        {"wafer_id": "W2", "score": 0.92},
        {"wafer_id": "W3", "score": 0.10},   # EDS_MIN_SIMILARITY(0.5) 미만 → 제외
        {"wafer_id": "W4", "score": None},   # score 없음 → 제외
        {"wafer_id": "W5", "score": 0.88},
    ])
    out = HttpEDSSearcher().search("W1", k=5)
    assert [r["wafer_id"] for r in out] == ["W2", "W5"]
    assert all(r["similarity"] >= config.EDS_MIN_SIMILARITY for r in out)


def test_http_search_truncates_to_k(monkeypatch):
    _patch_post(monkeypatch, [
        {"wafer_id": f"W{i}", "score": 0.9 - i * 0.01} for i in range(2, 8)
    ])
    out = HttpEDSSearcher().search("W1", k=3)
    assert len(out) == 3
