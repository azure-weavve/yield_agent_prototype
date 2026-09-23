# 증분 적재 재개 (incremental-load-resume)

## 목표

2026-08-06 에 멈춘 `feat/incremental-load` 를 끝내 main 에 병합한다.
원 설계·계획: `docs/superpowers/specs/2026-08-06-incremental-load-design.md`,
`docs/superpowers/plans/2026-08-06-incremental-load.md` (Task 1~6).
원장: 메인 작업 트리의 `.superpowers/sdd/2026-08-06-incremental-load/progress.md` (gitignore).

사용자 결정(원장·메모리에 기록, 유효): 증분 축 = root_lot · 변경 발견 = 검사일 ∪ 스텝 처리시각
· 라이브 DB 단일 트랜잭션 + 롤백 · tmp+swap 은 `--rebuild` 전용 · `--purge-before` 범위 밖
· 요청하지 않은 lot 이 실려 오면 fatal · `root_lot_id` strip 안 함.

## 기준

- 작업 위치: worktree `../prototype-incr` (브랜치 `feat/incremental-load`). 메인 트리는 Codex 와 공유라 건드리지 않는다.
- 2026-09-23 에 main(`2324f28`)을 브랜치로 병합했다: `4863e86`.
  - `tools/commonality.py` 충돌 → main 판 채택(브랜치 `fc7d8ef` 는 그 전 초안).
  - `tests/test_load_internal.py` 충돌 → 양쪽 추가 테스트 모두 유지.
  - **기준선 693 passed** (더미 DB 재생성 후. 스키마에 `step_history.root_lot_id` 가 생겨서 재생성이 필요하다).
- Task 1~3 완료. Task 4 는 fix 라운드 커밋(`3b3db33`) 후 재리뷰 전. Task 5·6 미착수.

## 코드 사실 (병합 후 확인)

- main 쪽 case-load-prep 이 `main()` 에 CSV 경로를 넣었다: `--yield-csv/--steps-csv/--yield-unit/--colmap`.
  CSV 는 `read_csv_records()` → `load()` → 전체 재적재. 더미 경로는 `resolve()` 로 비교해 CSV 에서는
  `--force` 로도 거부한다.
- 비-CSV 경로는 아직 인자 없이 `_extract()` → `load()` (전체 재적재)다. Task 5 가 없애려던 바로 그 동작이다.
- `load()`(`load_internal.py` 318)는 브랜치가 남긴 `rebuild()` 래퍼다.

## 설계 결정 (원 계획 Task 5 대비 수정)

**D1. CSV 입력을 네 번째 실행 모드로 넣는다.** 필수 상호배타 그룹 = `--rebuild | --since | --lots | --yield-csv`.
- 이유: 원 계획은 "모드 필수" 로 인자 누락 시 전체 재적재가 조용히 도는 것을 막는다. CSV 를 그룹 밖에 두면
  CSV 적재에도 `--rebuild` 를 요구하게 되거나(사례 적재 절차가 바뀜), 그룹을 선택으로 풀어야 한다(원 목적 훼손).
- CSV 모드의 의미는 지금과 같다: 사례 DB 로의 전체 재적재. `--steps-csv`·`--yield-unit` 필수와
  더미 경로 거부는 그대로다. `--since/--lots/--rebuild` 와 `--steps-csv`/`--yield-unit`/`--colmap` 을
  같이 주면 오류.
- 원 계획의 `db == Path(DB_PATH)` 비교 대신 병합본의 `is_dummy_path`(resolve 비교)를 쓴다 - main 이
  상대경로로 더미 보호가 뚫리는 것을 고친 판이다.

**D2. 테스트 수 기준선은 원 계획 숫자를 쓰지 않는다.** 693 기준으로 Task 5 = 693 + 새 테스트 수.
원 계획의 212/215 는 무효다.

## 구현 단계

1. owner: claude — **Task 4 재리뷰 (Opus)**: fix 라운드 `40bcddf..3b3db33` + 병합 커밋 `4863e86` 의
   의미적 통합(CSV 경로가 `root_lot_id` 가 생긴 `transform_steps`·`rebuild` 를 제대로 타는가,
   main 쪽 validate 변경과 브랜치의 `_scope` 좁히기가 충돌하지 않는가). 제품 코드 수정 없음.
2. owner: claude — Task 4 재리뷰 finding 수정 (Sonnet) → Opus 재리뷰. finding 없으면 생략.
3. owner: claude — **Task 5 (Sonnet)**: 원 계획 Task 5 + D1. 원 계획의 테스트 3개 + CSV 모드 테스트:
   - CSV 모드와 증분 모드를 함께 주면 오류(exit 2).
   - 인자 없이 실행하면 오류이고 stderr 에 `--rebuild` 가 나온다(원 계획 테스트).
   - 기존 CSV 테스트는 수정 없이 통과해야 한다(사례 적재 절차 불변).
   - 원 계획 Step 8 변이(청크 → 통째) 확인. 훼손 복원은 Edit/finally 로, `git checkout` 금지.
4. owner: claude — Task 5 리뷰 (Opus) → 수정 → 재리뷰.
5. owner: claude — **Task 6 (Sonnet)**: 원 계획 Task 6. 문서 파일명이 계획과 다르면 실제 파일을 찾아
   고친다(예: `docs/사내 데이터 변환 시 할 일.md`). 점검표에 CSV 사례 적재 모드 한 줄 추가.
6. owner: claude — **최종 전체 리뷰 (Opus)**: `main..feat/incremental-load` 전체 diff. 원장의 deferred
   minor 목록을 이때 판단한다(고칠 것 / 기록만 할 것).
7. 사용자 확인 후 main 병합. 병합 후 메인 트리의 `data/yield.db` 재생성이 필요하다(스키마 변경).

Codex 몫 없음 — 한 파일(`load_internal.py`) 중심의 직렬 작업이라 나누지 않는다.

## Task 4 재리뷰 결과 (Opus, 2026-09-23)와 결정

원 Important(요청 표기와 다른 lot) = **ADDRESSED**. BLOCKING 0. 병합 `4863e86` 의미적 통합 문제 없음.
다음은 고친다 (2단계 = Task 4 fix 라운드 2, 커밋 하나):

- **F1 (IMPORTANT-1)** 경로별 stray 테스트 2개: (a) yield 정상 + step 에만 정상 행과 `"B77B7 "` 행 혼재,
  (b) step 정상 + yield 에 `"B77B7 "` wafer 추가. 각각 **다른 쪽이 아니라 자기 쪽** `_collect_lots` 를 뺀 변이로
  단독 사망 확인. 지금 테스트는 두 경로를 동시에 어긋나게 보내 한쪽 감시만 남아도 통과한다.
- **F2** 롤백된 배치에서 `[전체]` 줄이 되돌려질 행을 포함해 찍힌다 → 롤백이면 생략하거나 "(롤백 전)" 표시.
- **F3** `test_a_broken_batch_is_blocked` 에 어느 검사가 잡았는지 메시지 단언 1줄.
- **F4** `load_incremental`: COMMIT 실패 시 `conn.close()` 보장(`finally`), ROLLBACK 이 다시 예외를 내도 원 예외가
  가려지지 않게 한다. 매일 도는 라이브 DB 경로라 잠금 경합이 현실적이다.

Task 5 에 함께 넣는다:

- **F5 (MINOR-1)** stray 비교를 실행 전체가 아니라 **청크마다** 한다(청크 2 가 청크 1 의 lot 을 실어 오면 이력 두 벌).
- **F6 (MINOR-2)** 요청했으나 0행인 lot 수를 리포트에 한 줄로 낸다(fatal 아님 - 원천에서 사라진 lot 은 정상일 수 있다).

Task 6 에 넣는다:

- **F7 (MINOR-3)** "구 스키마 DB(`root_lot_id` 없음)에는 첫 증분 전에 `--rebuild` 필수" 한 줄.

나머지 deferred minor 는 원장 기록으로 둔다(리뷰어 판단 목록 그대로).

## Task 5 리뷰 결과 (Opus, `4849d82`·`abb5657`)와 결정 — 닫힌 목록

BLOCKING 0. 아래 **G1~G9 만** 고친다(커밋 하나). 재리뷰는 이 목록이 닫혔는지 + 회귀 없음만 본다.
재리뷰에서 새로 나온 MINOR 는 고치지 않고 기록한다(리뷰 발산 방지).

- **G1 (I-1)** `load_incremental` 바깥 `except` 도 COMMIT 경로와 같은 모양으로: ROLLBACK 실패는 삼키고
  원 예외를 다시 던지며 `finally` 로 close. 그 경로 테스트 1개(SQLite 가 트랜잭션을 스스로 되돌린 상황 모사).
- **G2 (I-2 + MINOR-1)** 전역 stray 블록과 `requested_lots`/`seen_lots` 를 지우고 **청크 검사 하나만** 남긴다.
  청크 메시지는 사실만: "이 청크가 요청하지 않은 root_lot 을 실었다 - 추출 계약 위반" 류. F1 테스트 단언은 청크 메시지
  전용 문구로 좁힌다. yield 쪽 "앞 청크 lot 누수" 테스트 1개 추가. 경로별(yield/step) 청크 감시 변이가 각각 단독 사망해야 한다.
- **G3 (I-3)** `--rebuild` 청크 추출 테스트 1개(`test_extraction_runs_once_per_chunk` 의 rebuild 판). 변이 `rebuild_whole` 로 단독 사망 확인.
- **G4 (MINOR-2)** 롤백 시 `[증분]` 삭제 행 수를 실제 삭제처럼 찍지 않는다(F2 와 같은 처리).
- **G5 (MINOR-3)** `--since` 음수는 `ap.error`.
- **G6 (MINOR-4)** `--lots` 가 비면(공백·쉼표만) `ap.error`.
- **G7 (MINOR-5)** 증분 모드의 더미 경고 문구를 "lot 단위로 갱신됩니다" 류로. `--rebuild` 는 "대체" 그대로.
- **G8 (MINOR-6)** 정리용 ROLLBACK 자체가 실패하는 분기 테스트(내부 try 제거 변이로 단독 사망).
- **G9 (MINOR-7)** 0행 lot 줄: 커밋된 경우 "이번 커밋으로 DB 에서 지워졌다" 를 덧붙인다.

기록만: MINOR-8(`--lots` strip 미잠금, `LOAD_LOT_CHUNK<=0` 미검증), `--yield-csv ""` 트레이스백.

## 진행 기록

- `4849d82` Task 4 fix 2차(F1~F4) · `abb5657` Task 5(D1·F5·F6) · `802e557` G1~G9 · `8a86307` Task 6(F7 포함).
- `802e557` 재리뷰(Opus): BLOCKING/IMPORTANT 0. G1·G3~G9 닫힘. G2 는 메시지 문구가 반만 닫혀 Claude main 이
  직접 고쳤다(청크 stray 메시지·주석을 사실대로: 표기 다른 lot = 누적, 다른 청크 lot = 삭제 타이밍 어긋남). 713 passed.
- 기록만(고치지 않음): G9 롤백 분기 미잠금, G7 테스트가 `--since` 분기만 봄, MINOR-8, `--yield-csv ""` 트레이스백,
  `802e557` 커밋 메시지 한 글자 인코딩 깨짐.

## 최종 리뷰 결과 (Opus, main...branch 전체)와 결정 — 닫힌 목록 H1~H7

BLOCKING 0. 사용자 결정(2026-09-23): I-1 은 스텝 처리시각 축을 좁힌다, I-2 는 지금 고친다.

- **H1 (I-1, 사용자 결정)** `--since` 두 번째 축을 **yield 원천에 이미 있는 lot** 으로 좁힌다:
  `처리시각 >= since AND root_lot_id IN (SELECT root_lot_id FROM <수율원천>)`. 이유: 검사 전 재공 lot 은
  yield 가 없어 이력이 고아로 잡혀 매일 롤백되거나 고아 경고가 상시화된다(원 설계가 날짜 축을 버린 이유와 같다).
  "검사 후 재작업을 잡는다" 는 원 취지는 유지되고, 재공 lot 은 검사 뒤 검사일 축으로 들어온다.
  고칠 곳: `_extract_lot_ids` docstring, 모듈 docstring 계약 블록, 점검표 3-5 예시 SQL, 그 밖에 이 축을 설명하는 문서.
- **H2 (I-2)** `--rebuild` 에도 청크별 요청 대 납품 검사. `main()` 이 청크 lot 목록을 함께 넘기고 stray 면 fatal
  (교체 안 함). CSV/`load()` 경로는 요청 lot 개념이 없으므로 동작 불변(기존 CSV 테스트 무수정 통과).
  테스트: 청크 2 가 청크 1 lot 의 step 행을 실어 오면 swapped False. 검사 제거 변이로 단독 사망.
- **H3 (I-3)** 점검표 3-1 에 "적재 중에는 같은 DB 읽기가 막힌다(에이전트 `database is locked`), 반대로 긴 읽기가
  걸려 있으면 COMMIT 이 실패해 롤백된다 - 에이전트가 쉬는 시간에 돌린다" 한 줄.
- **H4 (M-4)** "구 스키마 DB 는 첫 증분 전 `--rebuild`" 문구에서 `data/cases/*.db` 를 뺀다. 사례 DB 는 증분 대상이
  아니고 읽는 코드가 `step_history.root_lot_id` 를 안 쓴다(`tools/commonality.py` 는 yield 에서 root_lot 을 읽음).
- **H5 (M-6)** 점검표 "더미/운영 DB 경로는 거부된다" 를 코드대로: `ya_config.DB_PATH` 와 같은 경로만 CSV 모드에서 거부.
- **H6 (M-7)** `.gitignore` 에 `*.db-journal`, `*.db.tmp` 추가(크래시 뒤 hot journal 은 복구에 필요한 파일).
- **H7 (M-5)** `--lots` 빈 값 검사를 더미 경고보다 앞으로.

기록만: M-1(`--since` 에서 한 청크가 통째로 0행이면 추출 장애일 가능성 - 재고 후보), M-2(yield stray 가 기존 lot 이면
IntegrityError 트레이스백), M-3(없는 `--db` 경로에 0바이트 파일), M-8(메모리 상한은 청크 2개), M-9(문서 예시 천 단위 쉼표).

## 수용 기준

- 전체 스위트 통과(693 + 새 테스트), 회귀 0.
- 모드 없는 실행이 오류로 멈춘다. `_extract` 가 청크 단위로 불린다(변이로 확인).
- CSV 사례 적재 명령(`--yield-csv ... --steps-csv ... --yield-unit ... --db data/cases/caseNN.db`)이 그대로 동작.
- 각 단계 Opus BLOCKING 0.

## 열린 질문 / 가정

- 가정: 사내 `_extract_lot_ids`/`_extract` 는 사용자가 사내에서 직접 채운다(원 설계 그대로).

## H1~H7 재확인 결과 (Opus, `c62b0bb..3549700`)

- H1~H7 전부 닫힘, 회귀 없음, BLOCKING/IMPORTANT 0. 병합 판정: 병합 가능.
- 리뷰어 권고(우선순위 높음) M4 변이 생존 = `--rebuild` CLI 가 청크 lot 목록을 넘기는 배선이 안 잠김 →
  Claude main 이 `test_h2_rebuild_cli_passes_chunk_lots_so_a_leak_blocks_the_swap` 추가. 2-튜플로 되돌린 변이에서 단독 사망 확인. 716 passed.
- 기록만: rebuild yield 쪽 청크 감시 미잠금(M3, 다른 청크 yield 누수는 PK 충돌로 멈춤) · rebuild 원소를 `len()` 으로
  가르며 비튜플 원소 계약이 좁아짐(시끄럽게 실패) · rebuild stray 문구가 "요청 밖 표기 lot" 경우를 설명 안 함 ·
  H1 축은 root_lot 단위라 lot 내 일부 wafer 재공이면 고아 경고 가능(H1 이전부터) · `docs/superpowers/` 스냅샷엔 옛 UNION.
