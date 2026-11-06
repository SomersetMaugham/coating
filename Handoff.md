# Handoff — 다음 작업: Agent Friendly CLI 어댑터 구현

작성: 2026-11-07 (같은 날 앞선 Handoff를 대체)

## 현재 상태
- 브랜치 `agent-cli`(`53acd17`)에 **계획 v2만 커밋**돼 있습니다: [`docs/CLI_PLAN.md`](docs/CLI_PLAN.md). 코드는 아직 바꾸지 않았습니다.
- `main`(`d83b9c2`)은 그대로입니다. PR은 아직 만들지 않았습니다.
- 지금까지 한 일:
  1. 코드 조사: CLI가 쓸 엔진 진입점과 `gui/` 안에 갇힌 로직을 찾았습니다(계획 6절).
  2. 계획 v1 작성
  3. Argon 리뷰(DEVELOPMENT_HISTORY 2.2절 방식, 첫 실행에 거부 없이 끝남)
  4. 지적 14건을 모두 `파일:줄`로 직접 확인했습니다(14건 모두 맞음).
  5. 계획 v2 작성: 판정표는 계획 12절에 있습니다.
- 공통 규칙은 [`AGENTS.md`](AGENTS.md)에, 이전 기능의 설계 이력은 [`docs/DEVELOPMENT_HISTORY.md`](docs/DEVELOPMENT_HISTORY.md)에 있습니다.

## 다음 세션 시작 프롬프트
> `docs/CLI_PLAN.md`(계획 v2)를 읽고 `agent-cli` 브랜치에서 구현해줘. 커밋은 계획 10절대로 3개로 나눠줘.
> 시작 전에 11절 남은 질문(N1, N2)을 먼저 확인해줘.

## 구현 전에 정할 점 (계획 11절)
- **N1**: GUI 진단 패널도 혼합물 성분까지 펼쳐 검사할지. 계획은 이번에는 CLI만 넓히는 안입니다.
- **N2**: `optimize`가 유효한 설계를 하나도 찾지 못했을 때(`no_valid_design`) 종료 코드 4가 맞는지

## 구현할 때 주의할 점 (리뷰에서 나온 함정)
- `optimize()`는 반드시 `throttle_s=0.0`으로 부릅니다. 0.1이면 중단 요청과 `--timeout`이 무시됩니다(`optimizer.py:256-268`).
- JSON 직렬화 전에 NaN·Inf·numpy 타입을 재귀로 정리합니다. `allow_nan=False`만으로는 막지 못합니다.
- 파라미터 값은 SI이고 `param_unit()`은 표시 단위입니다. 둘을 그대로 짝지으면 안 됩니다.
- 모델 예외 묶음을 `core/solver.py`에 두면 순환 import가 생깁니다(`materials/models.py:18`).
- 새 `_ISSUES_EN` 문구 `material_cycle`에는 KO 항목이 필요합니다. `unknown_material`은 기존 KO 문구(`i18n_ko.py:227`)를 다시 씁니다.
- 검증 절차는 DEVELOPMENT_HISTORY 2.1절 6단계를 따릅니다.
  - `QT_QPA_PLATFORM=offscreen python -m pytest`를 실행합니다.
  - 진단 패널을 영문·한글로 오프스크린 캡처해 눈으로 확인합니다.
