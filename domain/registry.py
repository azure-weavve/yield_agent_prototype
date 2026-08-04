"""hypotheses.yaml 로드 + 스키마 검증 + LangChain 도구 동적 생성.

전문가는 YAML 만 편집한다. 여기(개발자 영역)는 그 선언을 실행 가능한 도구로 바꾼다.
"""

from pathlib import Path

import yaml
from langchain_core.tools import StructuredTool

from domain import engine

REQUIRED_FIELDS = ("id", "name", "description", "legend")
DEFAULT_PATH = Path(__file__).resolve().parent / "hypotheses.yaml"


def load_hypotheses(path=None):
    path = Path(path) if path else DEFAULT_PATH
    specs = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(specs, list):
        raise ValueError(f"{path}: 최상위가 가설 리스트가 아니다")
    for i, s in enumerate(specs):
        for f in REQUIRED_FIELDS:
            if f not in s:
                raise ValueError(f"가설 #{i}: 필수 필드 '{f}' 누락")
        legend = s["legend"]
        if not isinstance(legend, list) or not legend:
            raise ValueError(f"가설 '{s['id']}': legend 는 비어있지 않은 리스트여야 한다")
        for lvl in legend:
            if not isinstance(lvl, dict) or "level" not in lvl or "columns" not in lvl:
                raise ValueError(f"가설 '{s['id']}': 각 legend 레벨은 level·columns 를 가져야 한다")
            if not isinstance(lvl["columns"], list) or not lvl["columns"]:
                raise ValueError(f"가설 '{s['id']}': legend 레벨 columns 는 비어있지 않은 리스트")
    return specs


def build_tools(specs):
    tools = []
    for spec in specs:
        # 타입 힌트는 장식이 아니다 — LLM 에 나가는 인자 스키마가 여기서 나온다.
        # 빼면 인자가 `{}` (타입 없음)로 나가고, LLM 이 문자열을 넘겨도 스키마 위반이
        # 아니게 되어 글자 단위로 쪼개진 채 "이력 결측" 결과가 나온다(에러 없이 오답).
        # tests/test_agent_tools.py 가 전 도구에 대해 이것을 잠근다.
        def _run(group_ids: list[str], control_ids: list[str],
                 reason: str = "", _spec=spec):
            return engine.evaluate(_spec, group_ids, control_ids)
        tools.append(StructuredTool.from_function(
            func=_run, name=f"hyp_{spec['id']}",
            description=(spec["description"].strip() +
                         "\nreason: 이 가설을 확인하는 판단 이유를 한 문장으로 기술한다 (감사 기록)."),
        ))
    return tools
