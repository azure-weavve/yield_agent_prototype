"""센서 통계값 가져오기.

인터페이스 고정: (스텝, wafer 목록) 입력 -> 센서 통계값 행 반환.
내부 구현만 데모(로컬 sqlite) / 운영(사내 FDC HTTP) 으로 교체한다 — EDS 와 같은 패턴.

⚠️ 값은 트레이스가 아니라 **wafer 1장의 구간 통계값**이다. 구간·통계 종류는 센서
   이름에 들어 있다(rf_power_steady_avg). 이 계층은 이름을 해석하지 않는다.

캐시 DB 는 두지 않는다 — 분석당 수천~수만 행이라 캐시의 근거(트레이스 규모)가
없고, 무효화·수명·용량 정책이라는 새 문제만 생긴다. 사내 조회가 실제로 느린 것이
확인되면 이 계층 **뒤에** 붙인다 (호출부 계약은 그대로다).
"""

import sqlite3
from abc import ABC, abstractmethod

import ya_config

COLUMNS = ("wafer_id", "step_seq", "sensor_name", "value", "tkout_time")


class SensorStore(ABC):
    """센서 조회 인터페이스. 2단 계산은 이 타입에만 의존한다."""

    @abstractmethod
    def fetch(self, step_seq: str, wafer_ids: list[str]) -> list[dict]:
        """지목된 스텝에서 주어진 wafer 들의 센서 통계값 전부.

        fetch 단위가 (스텝 × wafer 전원)인 이유: 1단이 챔버를 지목한 근거는
        "대조군은 그 챔버를 안 거쳤다" 이므로, 챔버로 좁혀 뽑으면 대조군 표본이
        0 이 되어 비교가 성립하지 않는다.
        """
        ...


class LocalSensorStore(SensorStore):
    """데모용. yield.db 의 sensor_log 에서 조회."""

    def fetch(self, step_seq: str, wafer_ids: list[str]) -> list[dict]:
        if not wafer_ids:
            return []
        ph = ",".join("?" * len(wafer_ids))
        conn = sqlite3.connect(ya_config.DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                f"SELECT {', '.join(COLUMNS)} FROM sensor_log "
                f"WHERE step_seq = ? AND wafer_id IN ({ph})",
                [step_seq, *wafer_ids]).fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]


class HttpSensorStore(SensorStore):
    """운영용. 사내 FDC 호출. 응답 스키마는 실측 후 매핑을 맞춘다."""

    def fetch(self, step_seq: str, wafer_ids: list[str]) -> list[dict]:
        import requests

        if not wafer_ids:
            return []
        resp = requests.post(
            ya_config.SENSOR_HTTP_URL,
            json={"step_seq": step_seq, "wafer_ids": wafer_ids},
            verify=ya_config.EDS_HTTP_VERIFY,      # 같은 사내 인증서 정책
            timeout=30,
        )
        resp.raise_for_status()
        # ⚠️ 사내 응답 스키마 미확정 — 실측 후 이 매핑을 맞춘다 (EDS 에서 같은 일이 있었다)
        return [{k: r.get(k) for k in COLUMNS} for r in resp.json().get("rows", [])]


def get_store() -> SensorStore:
    """config.SENSOR_MODE 에 따라 구현 선택."""
    if ya_config.SENSOR_MODE == "local":
        return LocalSensorStore()
    if ya_config.SENSOR_MODE == "http":
        return HttpSensorStore()
    if ya_config.SENSOR_MODE == "off":
        # 이 경로로 오면 도구 등록 필터가 샌 것이다 (tools/agent_tools.py).
        # "알 수 없는 모드" 로 뭉뚱그리면 오타인지 배선 오류인지 구분이 안 된다.
        raise ValueError("SENSOR_MODE=off 인데 센서 조회가 호출됐다 - "
                         "compare_sensor_distribution 이 등록되지 않아야 한다")
    raise ValueError(f"알 수 없는 SENSOR_MODE: {ya_config.SENSOR_MODE}")
