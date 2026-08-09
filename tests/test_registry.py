"""레지스트리 로더·도구 생성 — legend 스키마."""

import pytest
import yaml
from domain import registry

VALID = [{"id": "eqp_ch_commonality", "name": "설비/챔버 공통성",
          "description": "타깃만 거친 (스텝, 설비/챔버)를 찾는다",
          "legend": [{"level": "equipment", "columns": ["eqp_id"]},
                     {"level": "chamber", "columns": ["eqp_id", "ch_id"]}]}]


def test_load_valid_yaml(tmp_path):
    p = tmp_path / "h.yaml"
    p.write_text(yaml.safe_dump(VALID, allow_unicode=True), encoding="utf-8")
    specs = registry.load_hypotheses(p)
    assert specs[0]["id"] == "eqp_ch_commonality"
    assert specs[0]["legend"][0]["level"] == "equipment"


def test_reject_missing_field(tmp_path):
    bad = [{"id": "x", "name": "n", "description": "d"}]  # legend 없음
    p = tmp_path / "h.yaml"; p.write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="legend"):
        registry.load_hypotheses(p)


def test_reject_malformed_legend(tmp_path):
    bad = [{"id": "x", "name": "n", "description": "d",
            "legend": [{"level": "eq"}]}]  # columns 없음
    p = tmp_path / "h.yaml"; p.write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="columns"):
        registry.load_hypotheses(p)


def test_reject_unknown_denominator(tmp_path):
    """denominator 오타가 조용히 무시되면 분모가 말없이 바뀐다."""
    bad = [{"id": "x", "name": "n", "description": "d",
            "legend": [{"level": "eq", "columns": ["eqp_id"],
                        "denominator": "everything"}]}]
    p = tmp_path / "h.yaml"; p.write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="denominator"):
        registry.load_hypotheses(p)


def test_build_tools_produces_named_callables():
    tools = registry.build_tools(VALID)
    assert tools[0].name == "hyp_eqp_ch_commonality"
    assert "설비" in tools[0].description


def test_real_yaml_loads_and_builds():
    """저장소의 실제 hypotheses.yaml 이 로드·빌드된다."""
    specs = registry.load_hypotheses()
    ids = {s["id"] for s in specs}
    assert "eqp_ch_commonality" in ids and "ppid_commonality" in ids
    assert {t.name for t in registry.build_tools(specs)} == {f"hyp_{i}" for i in ids}
