"""EDS 유사맵 추천 도구.

인터페이스 고정: wafer_id 입력 -> 유사 후보 리스트 반환.
내부 구현만 데모(로컬 hnswlib) / 운영(사내 Flask /search HTTP) 으로 교체한다.
"""

import json
from abc import ABC, abstractmethod

import config


class EDSSearcher(ABC):
    """유사맵 검색 인터페이스. 그래프는 이 타입에만 의존한다."""

    @abstractmethod
    def search(self, wafer_id: str, k: int = 5) -> list[dict]:
        """wafer_id 와 유사한 후보를 [{wafer_id, similarity}, ...] 로 반환.
        자기 자신은 제외하고, similarity 가 config.EDS_MIN_SIMILARITY 미만인
        후보도 제외한다 (그래서 결과가 k 보다 적을 수 있다)."""
        ...


class LocalEDSSearcher(EDSSearcher):
    """데모용. 로컬 hnswlib 인덱스에서 검색 (실제 HNSW 검색 로직 재사용)."""

    def __init__(self):
        import hnswlib  # 지연 import: http 모드에선 불필요

        meta = json.loads((config.EMB_DIR / "labels.json").read_text(encoding="utf-8"))
        self.wafer_ids: list[str] = meta["wafer_ids"]
        self.dim: int = meta["dim"]
        self._id_of = {w: i for i, w in enumerate(self.wafer_ids)}

        self.index = hnswlib.Index(space="cosine", dim=self.dim)
        self.index.load_index(
            str(config.EMB_DIR / "index.bin"), max_elements=len(self.wafer_ids)
        )
        self.index.set_ef(50)

    def search(self, wafer_id: str, k: int = 5) -> list[dict]:
        import numpy as np

        if wafer_id not in self._id_of:
            raise KeyError(f"알 수 없는 wafer_id: {wafer_id}")

        vec = self.index.get_items([self._id_of[wafer_id]])[0]
        # 자기 자신이 1순위로 잡히므로 k+1 조회 후 제외
        labels, dists = self.index.knn_query(
            np.array([vec], dtype=np.float32), k=k + 1
        )
        out = []
        for label, dist in zip(labels[0], dists[0]):
            cand = self.wafer_ids[label]
            if cand == wafer_id:
                continue
            sim = round(float(1 - dist), 3)
            if sim < config.EDS_MIN_SIMILARITY:
                continue
            out.append({"wafer_id": cand, "similarity": sim})
            if len(out) == k:
                break
        return out


class HttpEDSSearcher(EDSSearcher):
    """운영용. 사내 Flask /search 호출 (verify 처리). 사내망에서만 동작."""

    def search(self, wafer_id: str, k: int = 5) -> list[dict]:
        import requests

        resp = requests.post(
            config.EDS_HTTP_URL,
            json={"wafer_id": wafer_id, "k": k},  # ⚠️ 요청 스키마는 아직 미확정(응답만 확인됨)
            verify=config.EDS_HTTP_VERIFY,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        # 응답: {"query_wafer": {...}, "similar_wafers": [{rank, wafer_id, similarity, ...}]}
        #  - self 는 similar_wafers 에 없음(query_wafer 로 분리) → 자기 자신 필터 불필요
        #  - similarity 는 "클수록 유사" + 음수 스케일(예 -0.18 ~ -0.23), rank 오름차순 정렬
        out = []
        for r in data.get("similar_wafers", []):
            cand = r.get("wafer_id")
            sim = r.get("similarity")
            if cand is None or sim is None:
                continue
            # ⚠️ 절대 임계(EDS_MIN_SIMILARITY=0.5) 필터는 보류 — 이 음수 스케일과 맞지 않아
            #    적용 시 전량 제외됨. 실제 분포 확인 전까지는 서버 rank 순 + top-k 로만 컷.
            out.append({"wafer_id": cand, "similarity": round(float(sim), 4)})
            if len(out) == k:
                break
        return out


def get_searcher() -> EDSSearcher:
    """config.EDS_MODE 에 따라 구현 선택."""
    if config.EDS_MODE == "local":
        return LocalEDSSearcher()
    if config.EDS_MODE == "http":
        return HttpEDSSearcher()
    raise ValueError(f"알 수 없는 EDS_MODE: {config.EDS_MODE}")
