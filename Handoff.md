# Handoff — 다음 작업: Agent Friendly CLI 어댑터 구현

작성: 2026-11-07 (같은 날 앞선 Handoff를 대체)

## 현재 상태
- 브랜치 `agent-cli`에 **구현이 끝났습니다**(계획 `docs/CLI_PLAN.md` v6의 커밋 1~5). 테스트 167개가 모두 통과합니다.
  - 커밋 1: 엔진으로 옮긴 로직(수율 대역, 공차 격자, 사전 점검, 단위표) + 엔진 결함 수정
  - 커밋 2: `coating-cli` 본체(`examples`, `info`, `check`, `solve`, `optimize`, `tolerance`)
  - 커밋 3: 실험 루프(`build`/`spec`, `--journal`/`journal`, `bound`, `materials`, `fit`, `--corners`, `--restarts`, Rozanov 한계)
  - 커밋 4: `docs/AGENT_PLAYBOOK.md`, Claude Code 스킬 `.claude/skills/coating-experiment`, `AGENTS.md` 단락
  - 커밋 5: README(영·한), `AGENTS.md`, `DEVELOPMENT_HISTORY.md` 3.12절
- `main`(`d83b9c2`)은 그대로입니다. **PR은 아직 만들지 않았습니다.**
- 경과는 `DEVELOPMENT_HISTORY.md` 3.12절, 설계 근거는 `CLI_PLAN.md` 12절(리뷰·모의 실행·블라인드 테스트 기록)에 있습니다.

## 다음 세션 시작 프롬프트
> `agent-cli` 브랜치로 PR을 만들고 CI(3 OS × Python 3.10/3.13)가 통과하는지 확인해줘.

## 다음에 할 일
1. PR 생성 → CI 확인. Windows에서 깨질 수 있는 곳을 특히 봅니다: 신호 처리(SIGTERM은 POSIX만), 경로 구분자(실험 기록 스냅숏 경로는 `/`로 저장), subprocess 테스트.
2. (권장) 실제 CLI로 블라인드 테스트 재실행: 문서만 읽은 에이전트에게 S1·S2(계획 12.6절)를 **실제로 실행**하게 하고, 막히거나 짐작한 지점을 플레이북에 반영합니다.
3. 머지 전에 이 `Handoff.md`를 지우거나 `DEVELOPMENT_HISTORY.md`로 옮깁니다.

## 참고
- 작업 폴더의 `Salisbury 스크린.coat`는 사용자가 앱에서 저장한 파일입니다. 추적하지 않으며 커밋하지 않았습니다.
- Argon 리뷰용 읽기 전용 설정 파일은 세션 임시 폴더에 만들기 때문에 세션 사이에 사라질 수 있습니다. 리뷰 전에 다시 만드세요(DEVELOPMENT_HISTORY 2.2절의 JSON).
