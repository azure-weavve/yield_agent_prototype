"""레지스트리 로더·도구 생성 단위 테스트."""

import pytest
from domain import registry


VALID = [{"id": "chamber_concentration", "name": "챔버 편중",
          "description": "설비·챔버 조합 편중 확인", "comparison": "categorical_concentration",
          "column": "eq_chamber", "min_specificity": 0.9}]


def test_load_valid_yaml(tmp_path):
    import yaml
    p = tmp_path / "h.yaml"
    p.write_text(yaml.safe_dump(VALID, allow_unicode=True), encoding="utf-8")
    specs = registry.load_hypotheses(p)
    assert specs[0]["id"] == "chamber_concentration"


def test_reject_missing_field(tmp_path):
    import yaml
    bad = [{"id": "x", "name": "n", "description": "d", "comparison": "group_only_categorical"}]  # column 없음
    p = tmp_path / "h.yaml"; p.write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="column"):
        registry.load_hypotheses(p)


def test_reject_unknown_comparison(tmp_path):
    import yaml
    bad = [{"id": "x", "name": "n", "description": "d", "comparison": "bogus", "column": "c"}]
    p = tmp_path / "h.yaml"; p.write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="bogus"):
        registry.load_hypotheses(p)


def test_build_tools_produces_named_callables():
    tools = registry.build_tools(VALID)
    assert tools[0].name == "hyp_chamber_concentration"
    assert "챔버" in tools[0].description
