"""2단 센서 비교 (결정론적). 1단이 지목한 스텝에서 타깃/대조군의 분포를 가른다.

설계 원칙 (1단 commonality 와 같다):
- **p-value 를 쓰지 않는다.** 스텝당 센서가 수백 개라 α=0.05 면 우연히 수십 개가
  유의하다. 효과크기 랭킹 + 원시 표본 수를 실어 "후보이지 결론이 아님" 이 드러나게 한다.
- **wafer 별 원본값을 반환하지 않는다.** 반환은 top-K 절단으로 유계다.
- **결측을 신호로 만들지 않는다.** 센서 행이 없는 wafer 는 그 센서의 분모에서 빠진다.
"""

import statistics

import ya_config
from tools.sensor_store import get_store


def _effect_size(t: list[float], c: list[float]) -> float:
    """표준화 평균차(Cohen's d). 표본이 작으면 커지므로 n 을 함께 실어 보낸다."""
    if len(t) < 2 or len(c) < 2:
        return 0.0
    st, sc_ = statistics.stdev(t), statistics.stdev(c)
    pooled = (((len(t) - 1) * st ** 2 + (len(c) - 1) * sc_ ** 2)
              / (len(t) + len(c) - 2)) ** 0.5
    if pooled == 0:
        return 0.0
    return abs(statistics.mean(t) - statistics.mean(c)) / pooled


def compare_sensor_distribution(step_seq: str, group_ids: list[str],
                                control_ids: list[str]) -> dict:
    """지목된 스텝에서 두 그룹의 센서 분포를 비교해 효과크기 top-K 후보를 낸다.

    status:
      - "insufficient_sample" : 한쪽 그룹의 표본이 비교에 못 미침
      - "fetch_failed"        : 원본 조회 실패 (결과 없음과 구분한다)
      - "no_signal"           : 계산은 됐으나 갈리는 센서가 없음
      - "ok"
    """
    targets = sorted(set(group_ids or []))
    controls = sorted(set(control_ids or []) - set(targets))

    base = {"candidates": [], "truncated": 0,
            "refetch_key": {"step_seq": step_seq,
                            "target_wafers": targets, "control_wafers": controls,
                            "sensors": [], "store_mode": ya_config.SENSOR_MODE}}

    if len(targets) < ya_config.SENSOR_MIN_SAMPLE or len(controls) < ya_config.SENSOR_MIN_SAMPLE:
        return {**base, "status": "insufficient_sample",
                "note": (f"타깃 {len(targets)}장 / 대조군 {len(controls)}장 — "
                         f"최소 {ya_config.SENSOR_MIN_SAMPLE}장 미만이라 비교하지 않는다. "
                         f"표본 2장짜리 효과크기는 허상이다.")}

    try:
        rows = get_store().fetch(step_seq, targets + controls)
    except Exception as e:                       # 조회 실패를 '결과 없음' 으로 오해하지 않게
        return {**base, "status": "fetch_failed",
                "note": f"센서 조회 실패: {type(e).__name__}: {e}"}

    tset = set(targets)
    by_sensor: dict[str, tuple[list, list]] = {}
    for r in rows:
        t_vals, c_vals = by_sensor.setdefault(r["sensor_name"], ([], []))
        (t_vals if r["wafer_id"] in tset else c_vals).append(r["value"])

    candidates = []
    for name, (t_vals, c_vals) in by_sensor.items():
        if len(t_vals) < 2 or len(c_vals) < 2:   # 결측으로 분모가 무너진 센서는 건너뛴다
            continue
        d = _effect_size(t_vals, c_vals)
        if d <= 0:
            continue
        candidates.append({
            "sensor_name": name,
            "effect_size": round(d, 3),
            "target_mean": round(statistics.mean(t_vals), 3),
            "control_mean": round(statistics.mean(c_vals), 3),
            "target_std": round(statistics.stdev(t_vals), 3),
            "control_std": round(statistics.stdev(c_vals), 3),
            "n_target": len(t_vals), "n_control": len(c_vals),
        })

    candidates.sort(key=lambda r: (-r["effect_size"], r["sensor_name"]))
    truncated = max(0, len(candidates) - ya_config.SENSOR_TOP_K)
    candidates = candidates[:ya_config.SENSOR_TOP_K]

    base["refetch_key"]["sensors"] = [c["sensor_name"] for c in candidates]
    if not candidates:
        return {**base, "status": "no_signal",
                "note": ("갈리는 센서가 없다. 1단이 지목한 챔버가 센서로는 설명되지 "
                         "않는다는 뜻이며, 원인 없음이 아니다.")}
    return {**base, "candidates": candidates, "truncated": truncated, "status": "ok",
            "note": ("후보는 결론이 아니다. 스텝당 센서가 수백 개라 우연한 분리가 흔하므로 "
                     "표본 수(n_target/n_control)를 반드시 함께 판단하라. "
                     "연동된 센서는 함께 움직이므로 순위만으로 원인을 가릴 수 없다.")}
