# Claude에서 Codex 앱 대화로 인계

Claude는 계획을 `docs/tasks/<작업명>/plan.md`에 작성한 뒤 저장소 루트에서 실행한다.

```powershell
python workflow.py run --task "docs/tasks/작업명" --dry-run
python workflow.py run --task "docs/tasks/작업명"
python workflow.py status --task "docs/tasks/작업명"
python workflow.py wait --task "docs/tasks/작업명" --timeout 3600
```

## 대상 대화

`workflow-config.json`의 `thread_id`로 지정한다. 초기 설정은 연결 테스트를 통과한
현재 앱 대화다. 다른 대화로 변경할 때는 해당 UUID를 설정하거나 run에
`--thread <대화 UUID>`를 명시한다. Claude의 현재 대화 ID를 자동 사용하지 않는다.
Codex 앱에서 대상 대화를 열어 진행과 추가 질문을 확인한다.

## 동작

1. 스크립트가 계획과 대상 UUID를 확인하고 실행별 요청 문서를 만든다.
2. `codex queue`로 요청 문서의 경로를 앱 대화에 전달한다.
3. 메인 Codex가 claim 명령으로 요청을 수락하고 running으로 기록한다.
4. Sol 서브에이전트가 구현하고 별도 Astra 서브에이전트가 검증한다.
5. 수정·재검증 후 메인이 finish 명령으로 최종 상태를 기록한다.
6. Claude는 status 또는 wait로 결과를 읽는다. 설계 수정은 Claude가 처리한다.

run의 queued 결과는 전송 접수일 뿐 구현 완료가 아니다.
대상 대화의 처리 상황에 따라 시작이 지연될 수 있다.
wait의 시간 초과는 기다리기를 끝내며 앱 작업을 중단하지 않는다.
run/wait 종료 코드는 정상 `0`, 입력·상태 오류 `2`, blocked `3`,
설계 수정 필요 `4`, 대기 시간 초과 `5`, 전송 불확실 `6`, abandon 상태 `7`이다.
status는 조회 성공 시 `0`이므로 JSON의 status를 읽는다.

## 상태와 중복 방지

- `queued`: 요청 접수됨, 작업 수락 대기.
- `running`: 앱 에이전트가 수락함.
- `complete`: 결과 문서와 모델 자기 보고를 검사하여 완료 처리됨.
- `needs_design_revision`: Claude의 설계 수정이 필요함.
- `blocked`: 작업을 마칠 수 없는 사유가 있음.
- `dispatch_unknown`: 전송 여부가 불확실함. 자동 재전송하지 않는다.

실행 중에는 저장소 전체에 하나의 인계만 허용한다. 활성 실행 기록은 run 명령 종료
후에도 유지된다. 이 장치는 사용자나 다른 도구의 직접 파일 편집까지 차단하지 않는다.

중단된 작업의 활성 기록을 해제할 때만 abandon 명령을 사용한다.
정확한 인자는 `python workflow.py abandon --help`로 확인한다.
이는 앱 메시지나 실행 중인 에이전트를 취소하지 않는다. 먼저 앱에서 작업을 중단하고
더 이상 파일을 수정하지 않는지 확인한다. 해제된 과거 요청의 claim/finish는 거부된다.

## 기록과 전제

최신 상태는 작업 폴더의 `.workflow/state.json`, 실행별 요청·로그·상태는
`.workflow/<실행 ID>/`에 남는다. 과거 로그는 보존하며 Git에서는 제외한다.

Python과 로그인된 Codex CLI가 필요하다. Windows에서는
`codex.cmd login status`로 확인한다. 인증·권한 설정을 자동으로 우회하지 않는다.
명령 접수에 실패하면 CLI와 앱이 같은 사용자 환경을 사용하는지 확인한다.

모델은 Sol/Astra로 지정하지만 실제 모델명은 에이전트 보고다.
검사 통과가 서버 내부 모델의 독립 증명을 뜻하지 않는다.
커밋·푸시·배포와 계획 밖 변경은 자동으로 허용하지 않는다.

연결 기반: 설치된 CLI의 `codex queue --help` 및
[공식 App Server 문서](https://learn.chatgpt.com/docs/app-server).
