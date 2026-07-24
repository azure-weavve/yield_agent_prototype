"""HttpEDSSearcher 가 사내 응답 계약(similar_wafers 매핑·None 제외·top-k)을 지키는지.

사내 /search 응답은 self 를 query_wafer 로 분리하므로 similar_wafers 엔 자기 자신이 없고,
similarity 는 음수 스케일이라 절대 임계(EDS_MIN_SIMILARITY) 필터를 적용하지 않는다
(f13b591 "도메인지식 주입 준비" 참조 — 서버 rank 순 + top-k 로만 컷).
LocalEDSSearcher 는 hnswlib 인덱스 생성물이 필요하므로 여기서는 다루지 않는다 (E2E 가 커버).
"""

import requests

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
