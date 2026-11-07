# Handoff — 다음 작업: Agent Friendly CLI 어댑터 구현

작성: 2026-11-07 (같은 날 앞선 Handoff를 대체)

## 현재 상태
- 브랜치 `agent-cli`에 **구현이 끝났습니다**(계획 `docs/CLI_PLAN.md` v6의 커밋 1~5). 테스트 173개가 모두 통과합니다(CI 3 OS × Python 3.10/3.13 통과, PR #10).
  - 커밋 1: 엔진으로 옮긴 로직(수율 대역, 공차 격자, 사전 점검, 단위표) + 엔진 결함 수정
  - 커밋 2: `coating-cli` 본체(`examples`, `info`, `check`, `solve`, `optimize`, `tolerance`)
  - 커밋 3: 실험 루프(`build`/`spec`, `--journal`/`journal`, `bound`, `materials`, `fit`, `--corners`, `--restarts`, Rozanov 한계)
  - 커밋 4: `docs/AGENT_PLAYBOOK.md`, Claude Code 스킬 `.claude/skills/coating-experiment`, `AGENTS.md` 단락
  - 커밋 5: README(영·한), `AGENTS.md`, `DEVELOPMENT_HISTORY.md` 3.12절
- PR #10(https://github.com/SomersetMaugham/coating/pull/10)이 열려 있습니다. 실제 CLI 블라인드 테스트에서 나온 버그 2건과 개선은 마지막 커밋에 반영했습니다(`DEVELOPMENT_HISTORY.md` 3.12절).
- 경과는 `DEVELOPMENT_HISTORY.md` 3.12절, 설계 근거는 `CLI_PLAN.md` 12절(리뷰·모의 실행·블라인드 테스트 기록)에 있습니다.

## 다음 세션 시작 프롬프트
> PR #10의 CI 결과를 확인하고, 통과하면 `Handoff.md`를 정리한 뒤 머지해줘.

## 다음에 할 일
1. 마지막 커밋의 CI 확인.
2. 머지 전에 이 `Handoff.md`를 지웁니다(경과는 `DEVELOPMENT_HISTORY.md` 3.12절에 있음).

## 참고
- 작업 폴더의 `Salisbury 스크린.coat`는 사용자가 앱에서 저장한 파일입니다. 추적하지 않으며 커밋하지 않았습니다.
- Argon 리뷰용 읽기 전용 설정 파일은 세션 임시 폴더에 만들기 때문에 세션 사이에 사라질 수 있습니다. 리뷰 전에 다시 만드세요(DEVELOPMENT_HISTORY 2.2절의 JSON).
