# case-load-prep — P1-3 사례 자료를 받자마자 별도 DB 에 적재할 수 있게 한다

작성: 2026-09-23 · 설계자 Claude main

## 목표와 요구사항

P1-3 사례 자료(사용자가 직접 추출한 CSV)가 도착하면 **더미 DB 를 건드리지 않고** 사례별 DB 에
적재·검증하고, P1-4 에서 분석 도구가 그 DB 를 읽게 한다. 자료 대기 중에 할 수 있는 준비 작업이다.
(`docs/2026-09-22-프로젝트-방향.md` §6 "자료 대기 중 준비 가능")

요구사항:

1. `data/load_internal.py` 가 요청서 2-4 형식(CSV, UTF-8, 사례마다 수율 1개 + 공정 이력 1개,
   원천 컬럼명 + 대응표)을 읽어 기존 `load()` 에 넘긴다.
2. 수율 단위(% / 0~1)를 **사람이 명시**하게 한다. 비율이면 ×100 한다.
   (`validate()` 의 범위 검사 0~100 이 비율을 못 잡아 전부 저수율이 되는 함정 — 요청서 5-2)
3. CSV 입력일 때는 `--db` 를 **필수**로 한다. 기본값(= 더미 `data/yield.db`)으로 떨어지지 않게.
4. 사례 원천 자료·사례 DB 가 git 에 실수로 들어가지 않게 한다(사내 실데이터).
5. P1-4 결과 기록 양식을 만든다(결과를 보기 전 사전 기록 + 결과·정답 대조).

## 범위 / 제외 범위

### 범위

- `data/load_internal.py` — CSV 읽기 함수 + CLI 인자 (`owner: claude`)
- `tests/test_load_internal.py` — 신규 테스트 (`owner: claude`)
- `.gitignore` — `data/cases/` 추가 (`owner: claude`)
- `docs/tasks/case-load-prep/case-record-template.md` — 사례 기록 양식 (`owner: claude`, 문서)

### 제외 범위

- **`ya_config.DB_PATH` 를 환경변수화하지 않는다.** 아래 설계 결정 D1 참조.
- `_extract()`(사내 추출 라이브러리 연결 자리) — 그대로 둔다. CSV 는 별도 경로로 붙인다.
- `transform_*`·`load()`·`validate()`·DDL — 변경 금지. 검증 규칙 강화(예: 수율 비율 자동 감지)도
  하지 않는다. 사람의 단위 명시로 막는다.
- parquet 입력 — 요청서는 "CSV 또는 parquet" 이지만 사용자가 직접 추출하므로 CSV 로 받는다.
  (`pandas`/`pyarrow` 가 requirements 에 없다. 의존성 추가 불필요)
- P1-4 실행 스크립트(도구 직접 호출) — P1-4 에서 한다. EDS 인덱스·sensor_log 는 더미 기준이라
  사례 DB 와 맞지 않지만 P1-4 는 LLM·EDS·센서 없이 commonality 만 돌리므로 무관.
- 게이트·판정·통계 코드 — 동결 대상. 건드리지 않는다.
- git 커밋 — 작업 뒤 사용자 결정.

## 기준

- 브랜치 `main` @ `b26a61c`
- 테스트 기준선: **655 passed** (2026-09-23 실측. 추적 637 + 미추적
  `tests/test_workflow.py` 18).

## 계획 시점 미커밋 변경

- 수정: `docs/P1-3-원천추출-요청서.md`, `docs/README.md`, `docs/next_step_claude.md`
- 미추적: `docs/2026-09-22-프로젝트-방향.md`, `docs/commonality_analysis_graph_design.md`,
  `docs/commonality_분석방법.md`
- 제품 코드 미커밋 변경 없음. 이 작업은 위 문서들을 건드리지 않는다.

## 현재 구조 (코드 확인한 사실)

- `load(yield_records, step_records, db_path, verbose, force)` — iterable of dict 두 개를 받아
  `<db>.tmp` 에 적재 → `validate()` fatal 0 이면 원자 교체. 입력 계약은 파일 머리 주석.
- `transform_yield` 필수 키: `root_lot_id`, `wafer_id`|`wafer_no`, `lot_id`, `lot_type`,
  `yield`, `date`. 선택: `defect_type`.
- `transform_steps` 필수 키: `root_lot_id`, `wafer_id`|`wafer_no`, `step_seq`, `eqp_id`.
  선택(`.get`): `area`, `ch_id`, `ppid`, `timestamp`.
- 선택 필드는 `_text()` 가 빈 문자열을 NULL 로 바꾼다 → CSV 빈칸이 그대로 NULL 이 된다.
- `main()`: `--db`(기본 `ya_config.DB_PATH`), `--force`. 입력은 `_extract()` 뿐.
- 분석 도구는 **호출 시점에** `ya_config.DB_PATH` 속성을 읽는다
  (`tools/commonality.py:145`, `tools/yield_tools.py:14`, `tools/sensor_store.py:43`).
  `from ya_config import DB_PATH` 형태는 저장소에 없다. 테스트도 `monkeypatch.setattr(ya_config,
  "DB_PATH", db)` 로 이미 이렇게 바꿔 끼운다(`tests/test_commonality.py:123` 등).
- `.gitignore` 는 `data/yield.db` 만 무시한다. `data/cases/` 는 무시되지 않는다.

## 설계 결정

**D1. DB 경로는 환경변수로 열지 않는다. P1-4 실행 스크립트가 `ya_config.DB_PATH` 속성을 바꾼다.**
- 근거: 도구가 호출 시점에 속성을 읽으므로 코드 변경 없이 된다(테스트가 이미 그 방식).
- 환경변수를 쓰면 `ya_config` 가 `load_dotenv()` 를 하므로 `.env` 에 넣는 순간 전역이 사례 DB 로
  바뀌고, 더미를 직접 읽는 테스트(`test_dummy_data.py` 등)가 사례 DB 를 읽는다. 막으려면 conftest
  고정이 또 필요하다. 얻는 것 대비 위험이 크다.
- 제약(P1-4 로 넘김): `sqlite3.connect` 는 없는 경로에 빈 DB 를 조용히 만든다. P1-4 스크립트는
  경로 존재를 먼저 확인해야 한다.

**D2. CSV 는 stdlib `csv.DictReader`, 인코딩 `utf-8-sig`.** 엑셀 저장 BOM 을 흡수한다.
UTF-8 로 못 읽으면(예: cp949 로 저장) 파일명을 담아 멈춘다. 인코딩 추측은 하지 않는다.

**D3. 컬럼 대응표는 YAML 파일(선택).** 요청서가 "원천 컬럼명 그대로 + 대응표" 로 받는다.
```yaml
yield:            # 원천 컬럼명: 계약 키
  WF_NO: wafer_no
  YLD: yield
steps:
  OPER: step_seq
```
- 대응표에 없는 컬럼은 이름 그대로 통과한다(계약 키와 같으면 대응 불필요).
- 대응 결과 **필수 키가 헤더에 없으면 행을 읽기 전에** 파일명·빠진 키·실제 헤더를 담아 멈춘다.
- 두 원천 컬럼이 같은 계약 키로 대응되면 멈춘다(조용한 덮어쓰기 방지).
- 대응표의 원천 컬럼이 헤더에 없으면 멈춘다(오타를 조용히 넘기지 않는다).

**D4. `--yield-unit {percent,ratio}` 를 CSV 입력에서 필수로.** 기본값을 두지 않는다.
`ratio` 면 `float(yield) * 100`. 변환은 CSV 읽기 단계에서만 하고 `transform_yield` 는 그대로.

**D5. CLI 모양.** CSV 인자가 있으면 CSV 경로, 없으면 기존 `_extract()` 경로(동작 불변).
```
python data/load_internal.py --yield-csv data/cases/case01_yield.csv \
    --steps-csv data/cases/case01_steps.csv --yield-unit percent \
    --db data/cases/case01.db [--colmap data/cases/case01_map.yaml]
```
- `--yield-csv` 와 `--steps-csv` 는 둘 다 주거나 둘 다 안 준다.
- CSV 경로에서 `--db` 미지정 → 에러. `--db` 가 더미 경로(`ya_config.DB_PATH`)와 같으면 → 에러
  (`--force` 로도 못 넘긴다. `--force` 는 fatal 무시용이라 의미가 다르다).
- `--db` 의 기본값은 `_extract()` 경로를 위해 기존 그대로 둔다.
- argparse `help` 문구는 cp949 안 글자만(em-dash·이모지 금지 — `test_help_text_survives_a_cp949_console`).

**D6. 공정 이력은 스트리밍.** 수율 CSV 는 작아서 리스트로 읽어도 되지만, 공정 이력은
제너레이터로 넘긴다(`load()` 가 이미 배치 적재). 헤더 검증은 첫 행 읽기 전에 끝낸다.

**D7. `data/cases/` 를 `.gitignore` 에 추가.** 사례 CSV·대응표·사례 DB 를 여기 둔다.

## 인터페이스 변경

- 신규 함수(모듈 수준, 테스트에서 직접 호출):
  `read_csv_records(yield_csv, steps_csv, yield_unit, colmap=None) -> (list[dict], Iterator[dict])`
  이름·내부 분해는 구현 재량. 단 반환 형태는 `load()` 입력 계약과 같아야 한다.
- CLI 인자 4개 추가(`--yield-csv`, `--steps-csv`, `--yield-unit`, `--colmap`). `--db`·`--force` 불변.
- 기존 함수 시그니처 변경 없음.

## 구현 단계

1. `owner: claude` — `.gitignore` 에 `data/cases/` 추가. **완료(main, 2026-09-23).**
   검증: `git check-ignore data/cases/x.csv` 가 매치.
2. `owner: claude` (Sonnet 5) — `read_csv_records` + CLI 분기 (D2~D6).
3. `owner: claude` (Sonnet 5) — 테스트(아래 수용 기준 T1~T9).
4. `owner: claude` (Opus 5 high) — 2·3 리뷰. 지적 → Sonnet 수정 → 재리뷰.
5. `owner: claude` (main) — `case-record-template.md` 작성.

Codex 소관 없음. 전체가 파일 하나 + 테스트라 나눌 이유가 없다. 따라서 `workflow.py` 핸드오프
하지 않는다(CLAUDE.md "Do not hand off ... " 조건과 무관하게 넘길 범위가 없음).

## 실패·경계 동작

| 입력 | 동작 |
|---|---|
| 필수 컬럼 없음 (대응 후) | 행 읽기 전 ValueError: 파일·빠진 키·헤더 |
| 대응표 원천 컬럼이 헤더에 없음 | ValueError |
| 두 원천 컬럼 → 같은 계약 키 | ValueError |
| UTF-8 디코드 실패 | 파일명 담아 에러 |
| `yield` 빈칸/문자 | 기존대로 `float()` 에서 에러 (적재 중단, 기존 DB 보존 — `load()` 의 tmp 경로) |
| `ratio` 인데 값이 1 초과 | **멈추지 않는다**(범위 검사는 `validate()` 가 ×100 후 0~100 으로 잡음) |
| 선택 컬럼 빈칸 | NULL (`_text`) |
| CSV 경로 + `--db` 없음 / 더미 경로 | 에러, 파일 안 건드림 |

## 수용 기준 (테스트)

- T1 원천 컬럼명 + 대응표로 된 CSV 두 개 → `load()` 까지 왕복, 행 수·값 일치.
- T2 대응표 없이 계약 키 그대로의 CSV 도 적재된다.
- T3 BOM 붙은 UTF-8 CSV 의 첫 컬럼이 정상 인식된다.
- T4 `ratio` → 저장값 ×100, `percent` → 그대로.
- T5 필수 컬럼 누락 → ValueError, 메시지에 빠진 키 이름.
- T6 대응표 오타(헤더에 없는 원천 컬럼) → ValueError. 중복 대응 → ValueError.
- T7 선택 컬럼 빈칸 → DB 에 NULL (`ppid`, `ch_id`, `defect_type`).
- T8 CLI: CSV 인자 + `--db` 없음 → 0 이 아닌 종료, `--db` 가 `ya_config.DB_PATH` → 0 이 아닌 종료.
  두 경우 모두 대상 파일이 생성·변경되지 않는다(`ya_config.DB_PATH` 는 테스트에서 tmp 로 바꿔 검사 —
  실제 더미를 건드리지 않는다).
- T9 CLI 정상 경로(subprocess): tmp CSV → tmp DB 생성, 종료코드 0.
- 기존 스위트 전체 통과(기준선 대비 신규 테스트 수만큼만 증가).
- 훼손 확인: `ratio` 변환을 지우면 T4 가, 필수 컬럼 검사를 지우면 T5 가 실패하는지 확인
  (복원은 `finally` 로).

## 열린 질문 / 가정

- 가정: 사용자가 CSV(UTF-8)로 추출한다. parquet 로 오면 이 작업 범위 밖(pandas 추가 여부를 그때 결정).
- 가정: 사례 1건 = root_lot 1개 이상, 파일 쌍 1개. 여러 사례를 한 DB 에 합치지 않는다(사례별 DB).
- 실제 원천 컬럼명은 샘플이 와야 안다. 대응표 방식이라 코드 변경 없이 흡수되는 것이 목표.

## 결과 (2026-09-23)

- 단계 1~5 완료. 스위트 **677 passed** (기준선 655 + 신규 22). 커밋 안 함(사용자 결정).
- Opus 1차 리뷰: BLOCKING 1(상대경로 `--db data/yield.db` 로 더미 가드 우회) + MINOR 4 + NIT 2.
  #1~#5·#7 수정. #6(수율 빈칸 에러에 파일·행 정보 없음)은 계획표대로 수용.
- 계획 대비 추가된 거부 규칙(리뷰 반영, 설계 의도 안):
  대응 후 헤더 전체에서 이름 중복 → 멈춤(통과 컬럼과의 충돌 포함) · 대응표가 만든 `wafer_id`/`wafer_no` 동시 존재 → 멈춤 ·
  대응표 구조(최상위 dict, 섹션 ⊆ {yield, steps}, 대상 ⊆ 계약 키) 검증 · `--yield-unit`/`--colmap` 단독 사용 → 멈춤.
- Opus 재리뷰: BLOCKING 0. 변이 9종(M1~M9) 전부 판별 확인.
- 남은 NIT (코드 변경 안 함):
  - N1 엑셀 CSV 끝에 이름 없는 빈 컬럼이 2개 이상이면 `['']` 중복으로 멈춘다(원인 표시하며 멈춤, 조용한 실패 아님).
    실제 파일이 그렇게 오면 그때 `""` 만 중복 검사에서 빼거나 추출 시 제거.
  - N2 대응표 없이 원천에 `wafer_id`·`wafer_no` 가 둘 다 있으면 `wafer_no` 우선(기존 계약). 실제 CSV 보고 판단.
