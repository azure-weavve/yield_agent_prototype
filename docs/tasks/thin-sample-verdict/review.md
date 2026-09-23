# thin-sample-verdict 독립 리뷰

- 실행 ID: `15397151-bd9f-4cfa-80a8-44bad6f8bb45`
- 리뷰 모델: `gpt-6-astra` (실제 사용 모델 보고이며 독립 로그 증명이라는 뜻은 아님)
- 기준: `eeb2eb58c6eee71f8358726fbf7a8af7fe592c0a` 대비 현재 미커밋 변경.
- 범위: README.md, graph/evidence.py, graph/nodes.py, graph/state.py, llm/client.py, tests/test_evidence.py, tests/test_graph_nodes.py, tests/test_mock_llm.py 및 관련 호출·보고 흐름.
- 제품/테스트 코드는 수정하지 않았으며 기존 사용자 변경을 보존했다.

## 확인된 결함

### R1 — P2: 혼합 weak_signal 판정에 표본 미달 건수 설명 누락

위치: `graph/nodes.py:694`의 weak_signal 판정문, `tests/test_graph_nodes.py:3869`.
`EQP_CH_BELOW_LINE + ALL_THIN[1]`을 빈손 제출하면 두 종류가 각각 1건 실리지만 판정문에는 잔차 1건만 언급된다. 계획 D7-1과 구현 단계 3은 이 경로에서도 별도의 표본 미달 건수 문장을 명시적으로 요구한다. 현재 T4는 final_claims의 두 종류와 잔차 문구만 검사하여 누락을 놓친다. 표시 상한 이후 실제 실린 표본 미달 수를 설명하고, 존재하지만 0건 실린 경우도 설명해야 한다.

### R2 — P2: 표본 미달 후보가 잔차를 밀어내면 없는 통과 근거와 잔차 줄을 보고

위치: `graph/nodes.py:1018`, `llm/client.py:264` 및 317.
위 혼합 픽스처에 `REPORT_MAX_EVIDENCE=1`을 적용하면 final_claims는 `ppid_commonality:ppid:CC002000:P1`, `passes=False`, `thin_sample=True` 하나다. 그런데 게이트는 "통과 근거가 상한을 채워" 잔차가 실리지 않았다고 말한다. 실제 통과 근거는 없다. 또한 mock의 `has_residual_lines = any(not c.get("passes", True) ...)`가 표본 미달을 잔차로 세어 결론에 "아래 [잔차] 줄이 그 후보들이다"를 붙인다. 실제 표기는 [표본 미달]이다. 상한 사유를 사실에 맞게 표현하고 mock도 좁힌 잔차 술어를 사용해야 한다. 이는 계획 완료 기준 4의 옛 술어 전수 점검이 누락한 자리다.

### R3 — P2: 지목 사유가 제출 후보 자체의 표본·점수 조건을 구분하지 않음

위치: `graph/nodes.py:687` weak_signal picked_note 및 `graph/nodes.py:794` thin_sample picked_note.
혼합 픽스처에서 score=1.0인 얇은 PPID 후보를 loop=2에서 지목하면 weak_signal이 "판별선을 넘지 못해 원인으로 확정하지 않았다"고 설명한다. 이 후보의 실패 원인은 타깃 표본이다. 반대 방향으로 (2c)는 정직한 비센서 지목이면 무조건 표본 미달로 설명하므로, 표본 충분·점수 아랫선 미만인 다른 후보를 지목해도 잘못된 사유를 붙인다. `_honest_pick`은 어떤 실재 후보든 허용한다. 실제 지목 후보의 조건에 따라 설명을 나누고 두 혼합 제출을 테스트해야 한다. 분기 우선순위나 하한 변경은 필요하지 않다.

### R4 — P2: thin_sample 판정문에 실제 타깃 카운트 누락

위치: `graph/nodes.py:802-807`.
계획 구현 단계 4와 자율 결정 범위는 "최고 점수와 타깃 카운트"를 판정문 필수 내용으로 요구한다. 현재는 최고 점수와 하한(2)만 표시하고 해당 후보의 실제 target_pass는 표시하지 않는다. 최고 점수 후보의 카운트와 하한을 함께 전달하고 단언해야 한다. 표시 상한으로 후보가 전부 잘려도 판정문이 해당 수치를 제공해야 한다.

## 독립 검증 결과

- `python -m pytest -q`: **608 passed in 14.66s**. 전체 회귀 스위트는 통과했다.
- `git diff --check`: 공백 오류 없음(CRLF 안내만 출력).
- 코드 대조: thin_sample의 구조적 술어·status 제한·잔차와의 서로소, (2a)/(2b)/(2c)/(2) 순서, 정직 지목/통과 후보 하한, 증거 적재, 라벨, 루프 한계 폐기 및 게이트리스 경로를 확인했다. 기존 residuals 정의와 기존 판정 하한은 보존됐다.
- 기존 테스트 픽스처를 `runpy.run_path`로 읽고 프로세스 내부에서만 상한을 1로 바꾸어 R1~R3의 weak_signal 측을 직접 재현했다. 저장소 파일은 변경하지 않았다. R3 반대 방향은 `_honest_pick` 및 else 분기 코드 검사로 확인했다.
- README 판정표와 state 어휘에 thin_sample 존재 확인.
- T1~T10의 기본 테스트는 있으나 T4의 필수 표본 미달 문구, 혼합 지목 및 두 종류 간 상한 경쟁은 잠그지 못했다.
- M1~M15는 handoff에 전부 CAUGHT로 보고되어 있다. 리뷰 중 제품/테스트 코드 수정 금지에 따라 독립적으로 변이를 주입하지 않았으며, 삭제된 임시 실행기의 결과는 독립 재현한 것으로 표시하지 않는다. 관련 단언은 검사했다.

## 완료 기준 판정 및 한계

1. 전체 스위트: 통과(608).
2. T1~T10 / M1~M15: 기본 테스트 통과, 변이 실행은 구현자 보고만 확인. 위 중요한 테스트 공백이 남음.
3. README/state 문서: 통과.
4. 옛 술어·거짓 문구 제거: 실패(R1~R3).
5. 판정문 필수 내용: 미충족(R4).

실서비스 LLM/실데이터 호출은 실행하지 않았다. 운영 프롬프트는 코드와 테스트로 검사했다. 확인되지 않은 별도 의심 사항은 없다.

## R1~R4 수정본 재검증

- R1~R4는 모두 해결됐다. 공용 지목 설명, 실제 표본 수, 두 종류의 절단 후 건수와 0건 사유, mock 잔차 술어를 확인했다.
- 독립 실행 `python -m pytest -q`: **612 passed in 14.86s**.
- `git diff --check` 통과. 추가 프로세스 내 검증에서 센서가 표시 상한을 차지해 얇은 후보가 0건 표시되어도 thin_sample 판정과 수치가 유지되고, 게이트리스 경로도 thin_sample로 종료함을 확인했다.
- 검사본 SHA256: graph/nodes.py `6e67871990d51f06f39c7abc794c087879bffb1151bc84c43d47dd63e45e48ce`, llm/client.py `b0f40b5363cead4827314c5868bb4949a9ba330e2735e899a9d6af92cb200a63`.
- handoff의 grep 0건 표현은 올바른 해석이 아니다. 실제 `not c.get("passes", True)`는 nodes.py와 client.py에 남지만 `and not c.get("thin_sample")`로 좁혀져 올바르다. 검사 기준은 문자열 부재가 아니라 잘못된 넓은 분류 술어의 부재다.

### R5 — P2: 분석 프롬프트가 이제 수락되는 얇은 지목을 반려된다고 설명

위치: `graph/nodes.py:48` ANALYZE_SYSTEM_PROMPT.
"잔차마저 없는 상태에서 지목하면 반려되고 같은 반려를 되풀이하면 루프 예산만 태운다"라는 운영 지시가 남아 있다. 잔차 없이 표본 미달 후보만 존재하고 그 후보를 지목하면 새 (2c)는 한계 전에도 즉시 수락한다(T2). 따라서 분석 LLM에 실제 게이트와 반대 계약을 알려주는 문장이 됐다. no_separation만 예외로 든 현재 문구에 thin_sample의 수락 조건과 표본 보충 조치를 반영하고 프롬프트 단언으로 잠가야 한다. 계획 D7의 기존 거짓 문장 제거와 완료 기준 4에 해당하며 분기나 하한 변경은 필요 없다.

관련 문서 정정: `llm/client.py:54-55`의 추상 generate_report 독스트링도 passes:false 항목을 전부 잔차로 설명하므로 표본 미달을 구분해야 한다.

**현재 최종 판정: 수정 필요.** R1~R4 해결, R5 수정 및 최종본 재검증이 남았다.
