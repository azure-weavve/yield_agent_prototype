# case-run-prep - P1-4 실행 스크립트를 사례 도착 전에 만들고 더미로 검증한다

작성: 2026-09-23 · 설계자 Claude main

## 목표와 요구사항

P1-3 사례 DB(`data/cases/caseNN.db`, `case-load-prep` 로 적재)에 대해 **LLM·EDS·센서 없이**
등록 가설 도구를 직접 호출하고, 결과를 사례 기록 양식(`docs/tasks/case-load-prep/case-record-template.md`)
2절·3절에 옮기기 쉬운 형태로 낸다. 사례가 오기 전에 도구를 확정해 두어 "정답을 보고 도구를 고치는"
일을 막는다(방향 문서 §6, 양식 6절).

요구사항:

1. `--db` 필수. **존재하지 않는 경로는 거부한다**(sqlite 가 빈 DB 를 조용히 만든다 - case-load-prep D1).
2. 타깃은 **명시 목록**으로 받는다(`--targets W1,W2,...`). EDS 형제 묶기를 하지 않는다 - 사례 DB 에는
   EDS 인덱스가 없고, 양식 2절은 "엔지니어가 처음 지목한 wafer 그대로" 를 요구한다.
   DB 에 없는 타깃 wafer 가 하나라도 있으면 목록을 보여 주고 멈춘다.
3. 대조군은 파이프라인과 **같은 함수**(`tools/grouping.py::select_control`)로 만든다.
   `insufficient` 면 파이프라인처럼 거기서 멈추고 그 사실을 보고한다(도구 호출 안 함).
4. 등록 가설 전부(`registry.load_hypotheses()`)를 `domain/engine.py::evaluate` 로 돌린다.
   가설이 읽는 테이블(`engine.TOOL_TABLES`)이 사례 DB 에 없으면 그 축은 **"미적재(테이블 없음)"** 로
   보고하고 건너뛴다(사례 DB 에는 metro 테이블이 없다 - `load_internal.py` DDL 확인).
   도구가 예외를 내면 그 축을 "도구 실패: <예외>" 로 보고하고 나머지 축은 계속 돈다.
5. 축 결과를 게이트와 **같은 코드**로 접고 순위를 매긴다:
   `evidence.build_bundle(findings)` → `bundle.ranked_groups()` → `evidence.groups_to_dicts()` →
   `evidence.format_group_line()`. 교락·포함관계·동점 문장이 그대로 나온다(양식 4절 (a)(b) 평가 재료).
6. 출력 두 가지:
   - stdout: 사람이 읽는 요약(아래 "출력 형식"). `ya_console.say` 로 찍는다(cp949 콘솔).
   - `--out <path.json>` (선택): 원시 결과 전부(대조군 결과, 축별 evaluate 반환값 그대로, 순위 묶음 dict).
7. 사례 DB 에 **쓰지 않는다**.

## 범위 / 제외 범위

### 범위 (전부 `owner: claude`)

- 신규 `data/run_case.py` - CLI + 함수 `run_case(db_path, targets) -> dict`, `render(result) -> str`
- 신규 `tests/test_run_case.py`
- 이 plan.md 결과 절

### 제외 범위

- 게이트 판정(`_gate_verdict`, finalize 판정문) - 동결 대상이고 LLM 제출이 전제다. 순위 묶음까지만 낸다.
- 잔차(`residuals`)·표본 미달(`thin_sample`) 별도 절 - 축별 표에 모든 후보와 `reject_reason` 이 실려 중복이다.
- 센서 2단, EDS, 대조군 확장, 설정 노브 변경 플래그 - 양식 6절(정답 뒤 실험)에서 필요하면 그때 한다.
- `ya_config` 변경, 도구·엔진·evidence 코드 변경 - 전부 읽기만 한다.
- 커밋 - 작업 뒤 사용자에게 보고하고 main 이 한다.

## 기준

- 브랜치 `main` @ `f1201ee`
- 테스트 기준선: **725 passed** (2026-09-23 실측, `python -m pytest -q`)
- 미커밋 변경: 없음(이 plan 제외)

## 현재 구조 (코드 확인한 사실)

- 도구는 **호출 시점에** `ya_config.DB_PATH` 를 읽는다(`tools/commonality.py:145`, `tools/yield_tools.py:14`).
  스크립트는 `ya_config.DB_PATH = Path(db)` 로 바꿔 끼운다. 테스트도 같은 방식(`monkeypatch.setattr`).
- `select_control(target_group)` → `{control_group, sources, insufficient, yield_summary}`.
  대조군 = 타깃과 같은 root_lot 의 비타깃 wafer 전원.
- `yt.get_wafers(ids)` 가 DB 에 있는 wafer 행만 준다 → 없는 타깃 판별에 쓴다
  (`grouping.normalize_target` 도 같은 방식이지만 단일 입력이면 EDS 를 부르므로 **쓰지 않는다**).
- `engine.evaluate(spec, group_ids, control_ids)` → `{hypothesis_id, legend, status, candidates[...], fdr_table,
  p_family_wise, p_family_wise_min_possible, meta, note}`. 후보마다 `claim_id, passes, reject_reason, score,
  target_pass/total, control_pass/total, p_permutation, p_min_possible, p_at_floor, n_reference, ...`.
- 순열 seed 고정(`tools/commonality.py::PERM_SEED`) → 같은 입력이면 같은 출력.
- `evidence.build_bundle(findings)` 는 `findings = [{"tool": "hyp_<id>", "result": <evaluate 반환>}, ...]` 를 받는다.
  도구 실패 축은 `{"tool": ..., "result": "<오류 문자열>", "failed": True}` 로 넣으면 `bundle.failed` 로 간다.
  tool 이름은 `registry.build_tools` 와 같게 `f"hyp_{spec['id']}"`.
- `load_internal.py` DDL 은 `yield`·`step_history` 두 테이블만 만든다. 더미 `data/yield.db` 에는 metro 가 있다.

## 설계 결정

**D1. 파이프라인 함수를 재사용하고 새 판단을 만들지 않는다.** 대조군·평가·접기·순위·문장은 전부 기존 함수다.
스크립트가 새로 판단하는 것은 (i) 없는 DB (ii) 없는 타깃 (iii) 없는 테이블 (iv) 도구 예외 네 가지 입력 처리뿐이다.
근거: P1-4 가 검증하려는 것은 엔진이다. 스크립트가 자기 규칙을 가지면 사례 결과가 엔진이 아니라 스크립트를 잰다.

**D2. 대조군 부족이면 멈춘다.** 파이프라인(status 노드)이 조기 종료하는 자리다. 여기서 도구를 돌리면
파이프라인이 절대 내지 않는 결과를 평가하게 된다. 양식 3절 "멈춘 곳" 에 적을 사실로 보고한다.

**D3. DB 경로는 존재만 확인하고, 더미 경로도 허용한다.** 읽기 전용이라 더미를 덮어쓸 위험이 없고,
더미로 스모크를 돌리는 것이 이 작업의 검증 수단이다. 대신 stdout 머리에 DB 절대경로를 찍는다.

**D4. 스크립트 끝에서 `ya_config.DB_PATH` 를 원래 값으로 되돌린다**(`try/finally`). `run_case()` 를 테스트나
노트북에서 부를 때 전역이 사례 DB 로 남지 않게 한다.

## 인터페이스

```
python data/run_case.py --db data/cases/case01.db --targets A45Z5_03,A45Z5_07 [--out data/cases/case01_run.json]
```

- 종료 코드: 0 = 정상(대조군 부족으로 멈춘 경우 포함 - 그것도 결과다), 2 = 입력 오류(없는 DB·폴더 DB, 읽을 수 없는 DB, 없는 타깃, 빈 타깃 목록, `--out` 이 `--db` 와 같은 파일·폴더·상위 폴더 없음).
- `run_case(db_path, targets) -> dict`:
  ```
  {
    "db": str(절대경로),
    "targets": [...],                       # 입력 순서 유지, 중복 제거
    "unknown_targets": [...],               # 비어 있지 않으면 여기서 끝 (axes 없음)
    "target_root_lots": {root_lot: n_target},
    "control": <select_control 반환값>,
    "stopped": None | "unknown_targets" | "control_insufficient",
    "axes": [{"hypothesis_id", "tool", "outcome": "ran"|"no_table"|"failed",
              "result": <evaluate 반환> | None, "error": str | None}],
    "groups": <groups_to_dicts 반환값>,     # 통과 후보 순위 묶음, 각 dict 에 "line" 추가(format_group_line)
    "settings": {COMMONALITY_PASS_MIN_SCORE, COMMONALITY_PASS_MIN_TARGET, COMMONALITY_PERMUTATIONS,
                 COMMONALITY_TOP_K, CONTROL_MIN_SIZE, RESIDUAL_MIN_SCORE},
  }
  ```
  없는 DB 는 `FileNotFoundError`, 빈 타깃은 `ValueError` - CLI 가 잡아 종료 코드 2.

## 출력 형식 (stdout, 양식 2·3절 순서)

```
[DB] <절대경로>
[타깃] n장: W1, W2 ...            root_lot 별 타깃 수: A45Z5 2
[대조군] n장 (root_lot 별: A45Z5 22) · 수율 중앙값 97.1 · 임계 90.0 미만 1장     <- insufficient 면 "부족 - 파이프라인은 여기서 멈춘다"
[설정] PASS_MIN_SCORE 0.5 · PASS_MIN_TARGET 2 · PERMUTATIONS 1000 · TOP_K 20 · CONTROL_MIN_SIZE 3
[축] hyp_eqp_ch_commonality  status=ok  후보 n (통과 m) · p_family_wise 0.01 (바닥 0.001)
  순위 | level | step | key | score | p (바닥, 바닥도달) | 타깃 a/b | 대조 c/d | 통과 | 제외 사유
  ...
[축] hyp_metro_commonality  미적재(테이블 없음: metro)
[축] hyp_x  도구 실패: KeyError: ...
[순위 묶음] (게이트와 같은 접기·순위, 통과 후보만)
  [1] <format_group_line 출력>
  ...
```
no_signal / no_paired_stratum / insufficient_group 이면 status 옆에 evaluate 의 `note` 를 한 줄로 붙인다.
정확한 열 구분·자릿수는 구현 자유다. **정보 항목은 위 목록이 닫힌 목록이다.**

## 구현 단계

1. `owner: claude` - `data/run_case.py` 작성 (`run_case`, `render`, `main`).
2. `owner: claude` - `tests/test_run_case.py` 작성 후 통과 → 전체 스위트 회귀 없음.
3. `owner: claude` - 더미 DB 스모크: 더미에서 저수율 lot 의 타깃 몇 장을 골라 실행, 출력을 결과 절에 붙인다.
4. Opus 리뷰(high) → 지적 수정 → 재리뷰.

Codex 인계 없음(전 범위 claude).

## 실패·경계 동작

| 입력 | 동작 |
|---|---|
| `--db` 경로 없음 | 오류 메시지, 종료 2, **파일이 생기지 않는다** |
| `--db` 가 폴더 | 없는 경로와 같게 처리, 종료 2 |
| `--db` 가 sqlite 로 읽히지 않음(0바이트·손상·스키마 불일치) | 오류 메시지(예외 원문 포함), 종료 2 |
| `--out` 이 `--db` 와 같은 파일(하드링크 포함)·폴더·상위 폴더 없음 | 도구 실행 전 거부, 종료 2, DB 불변 |
| 타깃 일부가 DB 에 없음 | 없는 목록 출력, 종료 2, 도구 호출 없음 |
| 타깃 1장 | 그대로 진행 → 도구가 `insufficient_group` 을 낸다(스크립트가 막지 않는다 - D1) |
| 대조군 < CONTROL_MIN_SIZE | 대조군 줄에 부족 표시, 축 실행 없음, 종료 0 |
| 가설 테이블 없음 | 그 축 `no_table`, 나머지 계속 |
| 도구 예외 | 그 축 `failed` + 예외 문자열. `tools_node`(`graph/nodes.py`)와 같은 모양으로 `build_bundle` 에도 `failed: True` 로 전달하지만(형식 통일), `build_bundle` 은 이 값을 `crashed` 집합에만 쓰고 최종 출력(`axes`/`groups`)에는 영향이 없다 - 실패 사실은 `axes[].outcome == "failed"` 로만 드러난다. 나머지 축은 계속 |
| 통과 후보 0 | 순위 묶음 절에 "(통과 후보 없음)" |

## 테스트 / 수용 기준

tmp_path 에 작은 sqlite DB 를 직접 만든다(`load_internal.load` 사용 가능, 또는 기존 테스트 픽스처 재사용 - 구현 자유).
metro 테이블 없는 DB 여야 한다(사례 DB 모양).

- A1 없는 DB 경로 → `FileNotFoundError`, **그 경로에 파일이 생기지 않는다**(단언).
- A2 없는 타깃 → `stopped == "unknown_targets"`, `axes == []`.
- A3 대조군 부족 → `stopped == "control_insufficient"`, `axes == []`.
- A4 정상: 심어 둔 원인 챔버(타깃만 거친 스텝·챔버)가 `groups[0]` 에 있다(rank 1). step_history 축 3개는
  `outcome == "ran"`, metro 축은 `outcome == "no_table"`.
- A5 도구 예외: `engine.TOOLS["step_history"]` 를 한 번 터지게 monkeypatch → 그 축 `failed`, 나머지 축은 `ran`,
  예외가 스크립트 밖으로 새지 않는다.
- A6 `run_case` 뒤 `ya_config.DB_PATH` 가 원래 값으로 돌아온다(예외 경로 포함).
- A7 `render()` 가 A4 결과에서 순위 묶음 줄(`format_group_line` 문자열)과 `미적재` 를 포함한다.
- A8 CLI: 없는 DB → 종료 2 / 정상 → 종료 0, `--out` JSON 이 `json.loads` 된다.
- A9 전체 스위트 725 + 신규, 회귀 0.
- A10 사례 DB 를 쓰지 않는다: 실행 전후 DB 파일 mtime·크기 동일.

## 열린 질문 / 가정

- 가정: 사례의 타깃은 wafer_id 로 주어진다(`{root_lot}_{no}` - `internal-lot-wafer-id-conventions`).
  lot 단위로 받게 되면 그때 옵션을 더한다.
- 가정: 순위 묶음은 통과 후보만. 사례에서 "통과 없음" 이 많이 나오면 잔차 절을 더할지 P1-4 에서 정한다.

## 결과

구현 완료 (owner: claude, 전 범위). Opus 리뷰(high) 결과 **pass, BLOCKING/MAJOR 0건** -
MINOR 5건(m1~m5)을 아래 "Opus 리뷰 반영" 절대로 반영했다.

**파일**
- 신규 `data/run_case.py` - `run_case(db_path, targets) -> dict`, `render(result) -> str`,
  `main(argv=None) -> int`. 다른 파일은 손대지 않았다.
- 신규 `tests/test_run_case.py` - A1~A10 + m1/m3 보강 테스트 전부 커버 (20개 테스트).

**설계 확인 사항 (계획 대비 변경 없음)**
- `graph/evidence.py::build_bundle` 는 findings 를 `[{"tool": f"hyp_{spec['id']}", "result": ...}]`
  형태로 받고, 실패 축은 `"failed": True` 를 더한다 - `graph/nodes.py:222-239` 실제 호출부로 확인.
  `no_table` 축은 findings 에 아예 안 넣는다(build_bundle 에 안 보낸다) - "안 돌린 축"과
  "실행됐다가 실패한 축"을 build_bundle 의 `ran`/`failed` 어휘와 섞지 않기 위해서다.
- `domain/hypotheses.yaml` 은 4개(`eqp_ch_commonality`, `ppid_commonality`,
  `step_passage_commonality` - 전부 tool=step_history, `metro_commonality` - tool=metro).
  사례 DB(metro 테이블 없음) 에서는 앞 3개가 `ran`, 뒤 하나가 `no_table` 이 된다 - plan 의
  가정과 일치.
- `tools/grouping.py::select_control` 은 `yt.get_wafers`/`yt.find_control_candidates` 만 쓰고
  EDS 를 안 부른다 - `normalize_target` 을 안 써도 되는 근거를 코드로 재확인.

**테스트**
- `python -m pytest -q tests/test_run_case.py` → **20 passed**.
- `python -m pytest -q` (전체) → **745 passed** (기준선 725 + 신규 20, 회귀 0).

**더미 DB 스모크**
```
python data/run_case.py --db data/yield.db --targets W2406_06,W2406_02,W2406_04 --out <tmp>/case_smoke.json
```
(`data/yield.db` 에서 `LOT2406` 이 평균 수율 90 미만인 lot 중 가장 낮았고, 그중 저수율
wafer 3장을 골랐다.)

출력 (일부, cp949 콘솔에서 정상 렌더링 확인):
```
[DB] C:\...\data\yield.db
[타깃] 3장: W2406_06, W2406_02, W2406_04            root_lot 별 타깃 수: LOT2406 3
[대조군] 4장 (root_lot 별: LOT2406 4) · 수율 중앙값 94.6 · 임계 90.0 미만 1장
[설정] PASS_MIN_SCORE 0.5 · PASS_MIN_TARGET 2 · PERMUTATIONS 1000 · TOP_K 20 · CONTROL_MIN_SIZE 3
[축] hyp_eqp_ch_commonality  status=ok  후보 2 (통과 1) · p_family_wise 0.0286 (바닥 0.0286)
  # | level | step | key | score | p (바닥, 바닥도달) | 타깃 | 대조 | 통과 | 제외 사유  (# = 도구 내 순서 - 게이트 등수가 아니다)
  1 | chamber | CC002000 | ETCH9_B | 1.0 | 0.0286 (0.0286, True) | 3/3 | 0/4 | True | -
  2 | equipment | CC002000 | ETCH9 | 0.25 | 0.5714 (0.0286, False) | 3/3 | 3/4 | False | 분리 점수 0.25 < 0.5
[축] hyp_ppid_commonality  status=ok  후보 1 (통과 1) · p_family_wise 0.0571 (바닥 0.0286)
  1 | ppid | CC002000 | PPID_X | 1.0 | 0.0286 (0.0286, True) | 3/3 | 0/4 | True | -
[축] hyp_step_passage_commonality  status=no_signal · ...  후보 0 (통과 0)
[축] hyp_metro_commonality  status=no_paired_stratum · ...  후보 0 (통과 0)
[순위 묶음] (게이트와 같은 접기·순위, 통과 후보만)
  [1] eqp_ch_commonality:chamber:CC002000:ETCH9_B · 분리 점수 1.0 · 타깃 3/3 통과 · 대조군 0/4 통과 ·
      순열 p 0.0286 (이 표본의 최소값) · 대상 W2406_02, W2406_04, W2406_06
        같은 wafer 를 PPID_X(ppid) 로도 설명할 수 있다 (교락) · ... - 현재 증거로는 구분되지 않는다 ...
[저장] <tmp>/case_smoke.json
```
`--out` JSON 은 `json.loads` 로 정상 파싱됨을 확인. 더미는 `data/yield.db` 에도 metro 테이블이
있어 `hyp_metro_commonality` 가 `no_table` 이 아니라 실제로 돌았다(`no_paired_stratum`) - 테이블
존재 판정이 "있으면 돌린다"로 정확히 동작함을 이 스모크가 추가로 확인해 준다.
`data/yield.db` 의 mtime·크기는 실행 전후 완전히 동일함을 확인(읽기 전용, A10 과 같은 검사).

**이탈 사항**: 없음. plan.md 의 인터페이스·출력 형식·설계 결정을 그대로 구현했다.

### Opus 리뷰 반영 (2026-09-23, high effort - pass, BLOCKING/MAJOR 0건)

- **m1** (테스트) - `_clean_case_db` 픽스처에 ppid 를 심어 **판별선을 못 넘는 후보**
  (`ppid_commonality:ppid:CC001000:PPID_X`, score 0.333 < 0.5)를 하나 실제로 내도록
  바꿨다. `test_normal_run_finds_planted_chamber_as_top_group` 에 두 단언을 추가:
  (i) 그 claim_id 가 `result["groups"]` 의 대표/교락/포함관계 어디에도 없다 -
  `ranked_groups()` 가 `self.passing()` 대신 `self.claims.values()`(미통과 포함 전부)를
  접는 훼손을 잡는다. (ii) `groups[0]["rolled_up_as"]` 에 굵은 해상도(설비 `ETCH9`)
  claim_id 가 실제로 들어 있다 - 접기 자체가 도는지 확인.
- **m3** (테스트) 3건 추가:
  (a) `test_cli_control_insufficient_exits_0_and_mentions_shortage` - A3 를 `main()` 으로
  실행하면 종료 0, 화면에 "부족" 이 찍힌다.
  (b) `test_single_target_is_insufficient_group_and_render_says_no_passing_groups` -
  타깃 1장이면 step_history 축 3개가 `insufficient_group` 상태로 `ran` 하고,
  `render()` 에 "(통과 후보 없음)" 이 찍힌다.
  (c) `test_duplicate_targets_deduplicated_preserving_order` - 중복 타깃이 입력 순서를
  지킨 채 한 번만 남는다.
- **m4** (코드+테스트) - `data/run_case.py`:
  - `run_case()` 의 존재 검사를 `db_path.exists()` → `db_path.is_file()` 로 좁혀
    디렉터리를 `--db` 로 주면 "없는 DB" 와 같은 자리에서 `FileNotFoundError` 로 막는다.
  - `main()` 에 `sqlite3.DatabaseError` catch 를 추가(0바이트 파일 등 "파일은 있는데
    sqlite DB 가 아니다" - 존재 검사로는 안 걸리고 실제 쿼리에서만 터진다는 것을
    실측으로 확인: 빈 파일은 `sqlite3.OperationalError: no such table: yield` 로
    터지며 이는 `DatabaseError` 의 서브클래스다).
  - `main()` 에서 `--out` 이 `--db` 와 같은 경로(`resolve()` 비교)이거나 `--out` 의
    상위 폴더가 없으면, 아무것도 돌리기 전에(`run_case()` 호출 전) 종료 2로 막는다.
  - 테스트 5건 추가: `test_directory_as_db_raises_same_as_missing`,
    `test_cli_directory_as_db_exits_2`, `test_cli_zero_byte_db_exits_2_with_clear_message`,
    `test_cli_out_equal_to_db_rejected_before_running`,
    `test_cli_out_parent_dir_missing_rejected_before_running`. 전부 실행 전/후 DB
    파일이 그대로임을(또는 파일이 안 생겼음을) 함께 확인한다.
- **m5** (코드) - 축별 후보 표의 열 이름 "순위" → "#" 로 개명하고 헤더 끝에
  "(# = 도구 내 순서 - 게이트 등수가 아니다)" 를 붙였다 - 이 번호는 도구가 낸 순서일
  뿐 게이트 등수(`[순위 묶음]` 절의 `rank`)가 아닌데 같은 "순위" 라는 말을 써서
  혼동을 줬다. cp949 콘솔에서 정상 렌더링 확인(em-dash 미사용, ASCII 하이픈만).
- **m2** (문서만, 코드 변경 없음) - "실패·경계 동작" 표의 "도구 예외" 행을 고쳐,
  `build_bundle` 에 `failed: True` 를 넘기는 것은 `graph/nodes.py::tools_node` 와
  모양을 맞추기 위한 것일 뿐 최종 출력(`axes`/`groups`)에는 영향이 없고, 실패
  사실은 `axes[].outcome == "failed"` 로만 드러난다는 것을 명시했다.

**m1 검증에 쓴 훼손(mutation) 확인**: `graph/evidence.py::Bundle.ranked_groups` 의
기본값을 `self.passing()` 대신 `self.claims.values()` 로 바꿔(직접 코드를 훼손) 로컬에서
`test_normal_run_finds_planted_chamber_as_top_group` 를 돌려 실패함을 확인한 뒤
원복했다(product 코드는 최종적으로 손대지 않았다) - "통과 후보만 접는다" 는 계약을
이 테스트가 실제로 지키는지 공허하지 않게 확인했다.

**재검증**
- `python -m pytest -q tests/test_run_case.py` → **20 passed**.
- `python -m pytest -q` (전체) → **745 passed** (기준선 725 + 신규 20, 회귀 0).
- 더미 DB 스모크 재실행(`data/yield.db`, 위와 동일 타깃) - "#" 헤더로 정상 렌더링,
  `data/yield.db` mtime·크기 실행 전후 동일 재확인.

**미완료**: 없음 - 구현 단계 1~4(Opus high 리뷰 포함) 전부 수행 완료. 커밋은 하지 않았다
(CLAUDE.md 워크플로 - main 이 보고 받은 뒤 진행).

### Opus 재리뷰 반영 (main 직접 수정)

재리뷰 판정 통과(BLOCKING/MAJOR 0). MINOR 처리:
- r2 반영: `--out` 과 `--db` 비교에 `os.path.samefile` 추가(하드링크).
- r3 반영: `--out` 이 폴더면 실행 전 거부. DB 오류 문구를 "손상, sqlite 아님, 스키마 불일치" 로 넓힘. 인터페이스·실패 표 갱신.
- r1 미반영: 순위 뒤집기 변이는 여기서 안 잡히지만 순위 계산은 기존 `ranked_groups`/`groups_to_dicts` 테스트가 잠근다. 스크립트는 순서를 그대로 옮긴다.
