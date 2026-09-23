# handoff-smoke-test — Claude → Codex 인계 연기 테스트 계획

## 목표와 요구사항

`workflow.py`가 시작하는 Claude → Codex 인계 경로가 실제로 동작하는지
최소 작업 하나로 확인한다. 검증 대상은 산출물의 난이도가 아니라 인계 경로다.

확인해야 할 것:

1. `workflow.py run` 이 Codex 관리 실행을 시작하고 구조화된 결과를 돌려준다.
2. 관리 실행이 AGENTS.md에 따라 `gpt-5.6-sol` 구현 에이전트와
   `gpt-6-astra` 검증 에이전트를 순서대로 운영한다.
3. `handoff.md`와 `review.md`가 이번 실행 내용으로 작성된다.
4. 계획의 완료 기준이 기계적으로 판정 가능하다.

구현 요구사항은 하나뿐이다.

- `docs/tasks/handoff-smoke-test/hello.txt` 를 생성한다.
- 내용은 `HANDOFF_OK` 한 줄이다.

## 작업 범위 및 제외 범위

### 범위

- `docs/tasks/handoff-smoke-test/hello.txt` 신규 생성
- `docs/tasks/handoff-smoke-test/handoff.md` 작성 (Sol)
- `docs/tasks/handoff-smoke-test/review.md` 작성 (Astra)
- `docs/tasks/handoff-smoke-test/.workflow/` 아래 스크립트가 남기는 실행 기록
  (스크립트가 쓴다. 에이전트는 수정하지 않는다.)

### 제외 범위

- 제품 코드(`graph/`, `tools/`, `main.py` 등) 수정 — 금지
- `tests/` 추가·수정 — 금지. 이 작업에는 자동화 테스트를 추가하지 않는다.
- 저장소 지침(`CLAUDE.md`, `AGENTS.md`), `workflow.py`, `.gitignore` 수정 — 금지
- 커밋, 푸시, 태그, 배포 — 금지
- 기존 미커밋 변경사항의 되돌림이나 정리 — 금지
- `hello.txt` 외의 파일을 이 디렉터리에 추가하는 것 — 위 4개 산출물 외에는 만들지 않는다

위 제외 항목 중 하나라도 필요해 보이면 그것은 구현이 아니라 설계 문제다.
`needs_design_revision` 으로 반환한다.

## 기준 브랜치와 커밋

- 브랜치: `main`
- 기준 커밋: `eeb2eb58c6eee71f8358726fbf7a8af7fe592c0a`

리뷰 대상 변경 범위는 이 커밋 이후 `docs/tasks/handoff-smoke-test/` 안에서
이번 실행이 만든 파일로 한정한다.

## 계획 시점에 존재하는 관련 미커밋 변경사항

`git status --porcelain` 기준 (계획 작성 시점):

- `M .gitignore` — `.workflow.lock` 과 `docs/tasks/*/.workflow/` 무시 규칙 추가.
  이 작업의 산출물이 아니다. 손대지 않는다.
- `?? AGENTS.md`, `?? CLAUDE.md`, `?? workflow.py`, `?? docs/codex-handoff.md`
  — 인계 워크플로우 자체. 이 작업의 대상이 아니다.
- `?? docs/2026-08-22-agent-direction-review.md`,
  `?? docs/2026-08-31-finalize-계약-영향범위.md`,
  `?? docs/2026-09-12-F-준비.md` — 무관한 조사 문서.
- `?? tests/test_workflow.py` — **다른 도구가 같은 워킹 트리에 만든 미추적 파일이다.**
  이 작업의 산출물이 아니고, 이 작업에서 읽거나 고치지 않는다.
- `?? docs/tasks/handoff-smoke-test/plan.md` — 이 계획서.

**중요: 위 변경사항은 전부 보존한다.** 이번 작업이 추가하는 것은
`docs/tasks/handoff-smoke-test/` 아래 파일뿐이다.

## 현재 코드 구조와 관련 파일

실제 코드에서 확인한 사실:

- `workflow.py` (저장소 루트, 미추적) — 인계 실행기.
  - `_task_dir()` 이 `--task` 가 `docs/tasks/` 아래인지, `plan.md` 가
    존재하고 비어 있지 않은지 검사한다. 아니면 `WorkflowError`.
  - `run()` 이 `.workflow.lock` 으로 저장소 전역 중복 실행을 막고,
    `codex exec -m gpt-6-astra -C <repo> -s workspace-write --json` 을
    `--output-schema`/`-o` 와 함께 실행한다. 프롬프트는 stdin 으로 넣는다.
  - `_validate_result()` 이 `complete` 를 엄격히 검사한다:
    `implementation_model == "gpt-5.6-sol"`, `review_model == "gpt-6-astra"`,
    그리고 `handoff.md`·`review.md` 각각이 **존재하고, 크기가 0이 아니며,
    (mtime_ns, size) 가 실행 직전과 달라야** 한다.
    이 중 하나라도 어긋나면 결과는 `blocked` 로 기록된다.
  - 종료 코드: 정상·dry-run `0`, 입력 오류 `2`, `blocked` `3`,
    `needs_design_revision` `4`.
- `AGENTS.md` (루트, 미추적) — 메인 Codex의 위임 절차, Sol/Astra 문서 요구사항.
- `docs/codex-handoff.md` — 실행 조건과 결과 처리.
- `docs/tasks/` 디렉터리는 이 계획으로 **처음 생성된다.**

## 설계 결정과 이유

### D1. 산출물을 텍스트 파일 하나로 제한한다

인계 경로의 실패와 구현의 실패를 섞지 않기 위해서다.
`hello.txt` 생성이 실패하면 원인은 구현 난이도가 아니라 인계 경로에 있다.

### D2. 산출물을 작업 디렉터리 안에 둔다

`docs/tasks/handoff-smoke-test/hello.txt` 는 제품 코드와 테스트에서 떨어져 있고,
저장소의 어떤 import·설정·테스트도 이 경로를 읽지 않는다.
따라서 이 작업은 기존 테스트 결과를 바꿀 수 없다. 이것이 완료 기준을
"기존 스위트 통과"가 아니라 "파일 내용 일치"로 잡는 근거다.

### D3. 파일 내용을 바이트 수준까지 정하지 않고 행 단위로 정한다

Windows 환경이라 도구에 따라 개행이 `LF` 또는 `CRLF` 가 될 수 있고,
마지막 개행 유무도 갈린다. 이것은 이 테스트가 보려는 대상이 아니다.
따라서 판정은 "개행을 제거한 유일한 내용 행이 `HANDOFF_OK`" 로 한다
(아래 완료 기준 C2). BOM 은 허용하지 않는다 — BOM 이 붙으면
첫 행 비교가 깨지므로 실패로 판정한다.

### D4. 자동화 테스트를 추가하지 않는다

완료 기준이 파일 한 개의 존재와 내용이고, 검증 명령이 두 줄이면 끝난다.
이 산출물을 위한 `tests/` 파일은 단발성 코드다. 만들지 않는다.
검증은 아래 명시된 명령으로 직접 실행하고 결과를 문서에 기록한다.

## 인터페이스 및 데이터 구조 변경과 호환성 조건

**없다.** 이 작업은 공개 인터페이스, 함수 시그니처, 데이터 구조,
설정 파일, 스키마를 전혀 건드리지 않는다.
새 파일 하나가 추가될 뿐이며 어떤 코드도 그 파일을 읽지 않는다.
따라서 호환성 조건도 없다.

인터페이스 변경이 필요하다고 판단된다면 계획 해석이 잘못된 것이다.
구현하지 말고 `needs_design_revision` 으로 반환한다.

## 단계별 구현 순서

### 1. 범위 확인 (Sol)

`docs/tasks/handoff-smoke-test/plan.md` 를 읽고 `git status --porcelain` 으로
위 "미커밋 변경사항" 절과 실제 상태를 대조한다.
→ 검증: 이 계획서가 기술한 변경사항 외에 이 작업이 건드릴 파일이 없음을 확인.

### 2. `hello.txt` 생성 (Sol)

`docs/tasks/handoff-smoke-test/hello.txt` 를 UTF-8(BOM 없음)로 쓰고
내용은 `HANDOFF_OK` 한 줄로 한다.
→ 검증: 아래 V1, V2 명령이 통과.

### 3. 변경 범위 확인 (Sol)

`git status --porcelain` 을 다시 실행해 새로 생긴 미추적 파일이
`docs/tasks/handoff-smoke-test/` 아래 것뿐인지 확인한다.
→ 검증: 아래 V3 명령의 출력이 허용 목록과 일치.

### 4. `handoff.md` 작성 (Sol)

AGENTS.md가 요구하는 항목(실제 구현 모델, 변경 내용, 완료 기준별 충족 여부와
근거, 실행한 검증 명령과 결과, 실행하지 못한 검증, 계획과 달라진 사항,
남은 문제, 리뷰 기준 커밋과 대상 변경 범위, 기존 사용자 변경과의 구분)을
모두 채운다. 실행하지 않은 명령의 결과를 적지 않는다.

### 5. 독립 검증 (Astra)

별도 컨텍스트의 `gpt-6-astra` 서브에이전트가 V1~V3을 직접 재실행하고
`review.md` 를 작성한다. 제품 코드와 산출물을 수정하지 않는다.
→ 검증: `review.md` 의 최종 판정이 "통과".

### 6. 수정·재검증 (필요 시)

지적이 있으면 기존 Sol 에이전트가 수정하고, Astra가 최신본을 재검증한다.

## 예외 상황과 실패 시 기대 동작

| 상황 | 기대 동작 |
|---|---|
| `gpt-5.6-sol` 또는 `gpt-6-astra` 를 생성할 수 없다 | 다른 모델로 대체하지 않는다. `blocked` 와 사유를 반환한다. |
| 서브에이전트 기능 자체를 쓸 수 없다 | 메인이 직접 구현하지 않는다. `blocked` 를 반환하고 제한 사항을 적는다. |
| `hello.txt` 가 이미 존재한다 | 내용이 완료 기준과 일치하면 그대로 두고 그 사실을 `handoff.md` 에 기록한다. 일치하지 않으면 기준에 맞게 덮어쓴다. |
| 제품 코드 수정이 필요해 보인다 | 이 계획으로는 불가능하다. 구현하지 말고 `needs_design_revision` 과 근거를 반환한다. |
| 검증 명령을 실행할 수 없다 | 통과했다고 적지 않는다. 실행하지 못한 사유를 적고 최종 판정을 "검증 미완료" 로 한다. |
| 워킹 트리에 계획에 없는 변경이 보인다 | 되돌리지 않는다. 위 "미커밋 변경사항" 절과 대조해 기존 사용자/타 도구 변경으로 구분해 기록한다. |
| 실행이 타임아웃되거나 중단된다 | 스크립트가 프로세스 트리를 종료하고 `blocked` 로 기록한다. 사용자가 `status` 로 확인한다. |

## 테스트 방법과 검증 가능한 완료 기준

자동화 테스트는 추가하지 않는다(D4). 아래 명령을 저장소 루트에서 실행한다.

### 검증 명령 (PowerShell)

```powershell
# V1: 파일 존재
Test-Path docs/tasks/handoff-smoke-test/hello.txt

# V2: 내용이 HANDOFF_OK 한 줄
$lines = @(Get-Content docs/tasks/handoff-smoke-test/hello.txt)
$lines.Count -eq 1 -and $lines[0] -ceq 'HANDOFF_OK'

# V3: 변경 범위가 작업 디렉터리 안에 갇혔는가
git status --porcelain
```

### 완료 기준

- **C1** — V1이 `True`.
- **C2** — V2가 `True`. 즉 개행을 제거한 내용 행이 정확히 하나이고
  그 값이 대소문자까지 `HANDOFF_OK` 다. 앞뒤 공백과 BOM 이 없다.
- **C3** — V3의 출력에서 이번 실행이 새로 만든 항목이
  `docs/tasks/handoff-smoke-test/` 아래뿐이다. 위 "미커밋 변경사항" 절에
  적힌 기존 항목은 **그대로 남아 있어야 한다**(사라지면 실패다).
- **C4** — `handoff.md` 가 존재하고 비어 있지 않으며
  AGENTS.md가 요구하는 항목을 채우고 실제 구현 모델을 적는다.
- **C5** — `review.md` 가 존재하고 비어 있지 않으며
  실제 검증 모델과 C1~C4 각각에 대한 독립 검증 결과, 최종 판정을 담는다.
- **C6** — 구조화된 결과의 `implementation_model` 이 `gpt-5.6-sol`,
  `review_model` 이 `gpt-6-astra` 다. 요청 모델 이름을 실제 사용 모델처럼
  적는 것은 금지한다 — 실제로 그 모델을 쓰지 못했다면 `blocked` 다.

C1~C6이 모두 충족될 때만 `complete` 다.

## 구현자 자율 결정 사항

- `hello.txt` 를 만드는 수단(에디터 도구, 셸 리다이렉션, 스크립트 중 무엇이든)
- 개행 문자가 `LF` 인지 `CRLF` 인지 (C2가 둘 다 허용한다)
- 마지막 행 뒤의 개행 유무 (C2가 둘 다 허용한다)
- `handoff.md`/`review.md` 의 문서 구조와 절 순서 (요구 항목을 모두 담는 한)
- V1~V3을 PowerShell 대신 동등한 다른 방법으로 실행하는 것
  (단, 무엇을 실행했고 무엇이 나왔는지 그대로 기록할 것)

## 설계 재검토가 필요한 사항

아래는 구현자가 판단하지 말고 `needs_design_revision` 으로 되돌린다.

- 제품 코드, `tests/`, 저장소 지침, `workflow.py`, `.gitignore` 수정이 필요한 경우
- `hello.txt` 의 경로나 내용을 바꿔야 한다고 판단되는 경우
- 완료 기준 C1~C6 중 어느 하나를 완화해야 한다고 판단되는 경우
- 커밋·푸시가 필요하다고 판단되는 경우

## 미해결 질문과 가정

### 코드에서 확인한 사실

- `workflow.py` 의 `_validate_result()` 는 `complete` 에서 두 문서의
  **신선도**(실행 직전 대비 mtime/size 변화)를 요구한다. 재실행 시
  기존 문서를 손대지 않으면 `blocked` 가 된다. (`_artifact_signature` 참조)
- `_task_dir()` 는 `plan.md` 가 비어 있으면 거부한다.
- 실행 샌드박스는 `workspace-write` 이고 권한 우회 옵션은 쓰지 않는다.
- Codex CLI 는 `C:\Users\Kwanghee\AppData\Roaming\npm\codex.cmd` 로 해석되고,
  `codex.cmd login status` 는 `Logged in using ChatGPT` 를 반환했다.
- `docs/tasks/` 는 이 계획 전에 존재하지 않았다.

### 설계상의 가정

- **A1** — `gpt-5.6-sol` 과 `gpt-6-astra` 가 현재 Codex CLI 실행 환경에서
  실제로 생성 가능한 모델이라고 가정한다. **이것은 미확인이다.**
  이 가정이 깨지면 결과는 `blocked` 이고, 그것도 이 테스트의 유효한 결과다
  (인계 경로가 모델 대체를 허용하지 않는다는 것을 확인해 준다).
- **A2** — `tests/test_workflow.py` 는 다른 도구가 만든 미추적 파일이며
  이 작업과 무관하다고 가정한다. 이 작업은 그 파일을 읽거나 고치지 않는다.
- **A3** — 실행 중 사용자나 다른 도구가 같은 작업 디렉터리를 동시에
  수정하지 않는다고 가정한다. 잠금은 `workflow.py` 실행끼리만 막는다.

### 미해결 질문

없다. A1의 결과는 실행이 답한다.
