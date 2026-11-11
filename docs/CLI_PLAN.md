# 계획 v6 — Agent Friendly CLI 어댑터

작성: 2026-11-07 · 브랜치 `agent-cli` · 상태: **v6 (블라인드 테스트 반영, 열린 질문 모두 결정, 구현 전)**
- v1 → v2: 1차 Argon 리뷰 반영(12.1·12.2절).
- v2 → v3: 목표 워크플로우를 "에이전트가 사용자의 현재 조성에서 출발해 목표에 도달할 때까지 스스로 실험한다"로 정하고,
  설계 명세(`build`/`spec`), 실험 기록(`--journal`), 물리 한계 검사(Rozanov), 에이전트 플레이북, 연결 방식 비교를 추가(13절).
- v3 → v4: 2차 Argon 리뷰 반영(12.3절). 명세를 `Project` 전체를 담도록 확장, Rozanov 적용 조건·정적 투자율 계산·판정 수준 수정,
  실험 기록의 비교 기준·시드 기록 추가, 연결 방식을 **CLI + Skill/플레이북**으로 결정.
- v4 → v5: 엔진을 직접 돌려 실험 루프를 모의 실행한 결과 반영(12.5절). `materials` 명령, 재료 형식 부록(부록 A),
  공차 분석의 목표 꼭짓점 평가(`--corners`)와 결합 수율, 혼합 모델 유효 범위 경고, 다중 시작(`--restarts`), 플레이북 보강.
- v5 → v6: 블라인드 테스트(문서만 읽은 Claude·agy 두 테스터, 시나리오 2개) 반영(12.6절). 명령별 출력 JSON(부록 B)과 `margin_db` 정의,
  플레이북 명령 정정, 수직 입사 Rozanov 판정 규칙 수정, 측정 재료 규칙(측정 범위, `fit`, wt% 분율, 파라미터 지어내기 금지), 표기 규칙 정리.
  바뀐 곳에는 "(v3)"~"(v6)"을 붙였습니다.

## 1. 문제

Coating Studio의 기능은 지금 GUI로만 쓸 수 있습니다. 코딩 에이전트(Claude Code, agy 등)나 스크립트가
`.coat` 파일을 계산·최적화·공차 분석하려면 Python API를 직접 짜야 하고, 그마저도 일부 로직
(수율 대역, 최적화 사전 점검, 단위 환산)이 `gui/` 안에 있어 Qt 없이 GUI와 같은 결과를 재현할 수 없습니다.

목표는 다음과 같습니다.
- 에이전트가 **한 번의 명령 호출로** 결과를 얻고, **stdout의 JSON 하나만 파싱하면** 성공·실패·부분 결과를 구분할 수 있게 합니다.
- **GUI와 같은 숫자**가 나오게 합니다(같은 격자, 같은 수율 기준, 같은 사전 점검).
- **Qt와 matplotlib을 import하지 않습니다**(AGENTS.md 계층 규칙). 디스플레이가 없는 서버에서도 동작해야 합니다.

## 2. 범위

| 하위 명령 | 하는 일 | 쓰는 엔진 API |
|---|---|---|
| `examples` | 내장 예제 목록 / 예제를 `.coat`로 저장 | `examples.EXAMPLES` |
| `info` | 프로젝트 요약: 층(index·uid·재료·두께), 재료, 목표, 변수, 최적화 가능한 파라미터 | `available_params`, `param_unit`, `get_param`, `material_users` |
| `check` | 모델 검증 + 시험 계산 + 재료 진단 + (변수가 있으면) 최적화 사전 점검 | `validate`, `solve`, `check_material`, `preflight` |
| `solve` | 주파수 / 각도 / 맵 스윕 계산과 요약 | `solve`, `power_to_db` |
| `optimize` | 최적화 실행, 결과 요약, 최적화된 `.coat` 저장(선택) | `preflight`, `optimize`, `apply_result`, `Project.save` |
| `tolerance` | 몬테카를로 공차 분석(밴드·수율) | `run_tolerance`, `yield_intervals`, `tolerance_frequencies` |
| `build` (v3) | 사람이 읽는 설계 명세(JSON) → `.coat` | 13.2절 |
| `spec` (v3) | `.coat` → 설계 명세(JSON). `build`의 역 | 13.2절 |
| `bound` (v3) | 파일 없이 목표만으로 Rozanov 최소 두께 계산 | 13.4절 |
| `journal` (v3) | 실험 기록 폴더 요약(시도 목록, 최선 설계) | 13.3절 |
| `materials` (v5) | 내장 재료 목록: 이름, 종류, note, 명세에 그대로 쓸 수 있는 재료 dict, 최적화 가능한 파라미터와 단위 | 13.7절 |
| `fit` (v6) | 측정 CSV를 Debye/Lorentz 분산 모델로 맞춰 재료 dict와 잔차를 냄 | 13.8절 |
| `invert-filler` (v7) | 복합재 측정 CSV에서 충전재의 유효 파라미터를 역산해 CSV로 씀 | 13.9절 |
| `fss-grid` (v8) | 메시·패치 치수에서 L 또는 C와 각도 계수, 유효 한계를 계산 | 13.10절 |
| `fit-shape` (v10) | 여러 함량의 복합재 측정에서 Odelevskiy 비율 N/pc와 시편별 허용 N 범위를 구함 | 13.11절 |
| `extract-nrw` (v11) | 측정한 2포트 `.s2p`에서 NRW로 시편의 ε(f), μ(f)를 구해 측정 CSV로 씀 | 13.12절 |
| `fit-gem` (v12) | 여러 함량의 복합재 측정에서 McLachlan GEM의 퍼콜레이션 임계값 pc와 지수 t를 구함 | 13.13절 |

(v3) `check`는 활성 목표마다 Rozanov 한계 판정(`result.limits`)을 함께 냅니다. `solve`·`optimize`·`tolerance`·`check`는 공통 옵션 `--journal DIR --note TEXT`를 받습니다.

**결과 내보내기**는 별도 하위 명령으로 두지 않고, 모든 명령의 공통 옵션 `--format json|csv`와
`--output PATH`로 처리합니다(4.4절). `optimize`가 최적화된 설계를 `.coat`로 저장하는 것도 내보내기에 속합니다.

### 넣지 않는 것 (v1)
- 재료·층을 하나씩 고치는 편집 명령, 파라미터 덮어쓰기(`--set PATH=VALUE`). 경로 튜플(공백·슬래시가 든 재료 이름, 정수 인덱스)을
  플래그 문자열로 모호하지 않게 표현하기 어렵습니다. (v3) 편집은 대신 **`spec`으로 꺼내 명세를 고치고 `build`로 다시 만드는** 왕복으로 합니다(13.2절).
- 그림(PNG/SVG) 출력. matplotlib 백엔드와 폰트 설정이 GUI 쪽에 묶여 있습니다.
- 측정 곡선 비교(`comparison.py`), Touchstone 입출력(DEVELOPMENT_HISTORY 6장 미룬 작업).
- 출력 번역(4.6절), `--progress-file`, JSON Schema 배포(`coating-cli schema`).
- PySide6를 `[gui]` extra로 분리하는 일(3절).

## 3. 실행 형태

- **새 콘솔 진입점** `coating-cli`를 `[project.scripts]`에 추가합니다 → `coating_studio.cli:main`.
  - 기존 `coating-studio`는 `[project.gui-scripts]`입니다. Windows에서는 콘솔이 붙지 않아 stdout이 사라지고,
    `gui/app.py:main`은 시작하자마자 PySide6를 import합니다. 그래서 하위 명령을 여기에 붙이지 않습니다.
- `python -m coating_studio.cli …`도 같은 진입점으로 동작합니다(`cli/__main__.py`).
- `python -m coating_studio`(`__main__.py`)는 지금처럼 GUI를 띄웁니다. 바꾸지 않습니다.
- PySide6는 계속 필수 의존성으로 둡니다. `[gui]` extra로 빼면 `pip install coating-studio`와 `pip install -e ".[dev]"`(AGENTS.md, CI)가
  GUI를 설치하지 않게 되기 때문입니다. AGENTS.md의 규칙은 import 경계 규칙이므로 테스트(9절 1번)로 지킵니다.

## 4. 출력 규약

### 4.1 stdout: JSON 문서 하나
모든 명령은 끝날 때 stdout에 **JSON 객체 하나**만 씁니다(`--output`으로 파일에 쓸 때도 stdout에는 봉투를 씁니다).
예외는 두 가지입니다: `--help`(argparse의 일반 텍스트, 종료 코드 0)와 `--format csv`를 `--output` 없이 쓸 때(4.4절).

```json
{
  "ok": true,
  "command": "solve",
  "cli_schema": 1,
  "app_version": "1.x.y",
  "input": {"path": "design.coat", "schema": 4},
  "result": { ... },
  "warnings": [ {"code": "demo_values", "level": "info", "material": "PMI foam", "message": "..."} ],
  "stopped": false
}
```

실패하면 다음과 같이 씁니다.

```json
{
  "ok": false,
  "command": "solve",
  "cli_schema": 1,
  "error": {"code": "material_out_of_range", "message": "...",
            "details": {"material": "...", "data_lo_hz": 2e9, "data_hi_hz": 12e9, "req_lo_hz": 1e9, "req_hi_hz": 18e9}}
}
```

- **불변식: `ok == (종료 코드가 0 또는 5)`.** 모든 하위 명령에서 지킵니다. `check`도 예외가 아닙니다(7절).
- `cli_schema`는 출력 형식의 버전입니다. 필드를 빼거나 의미를 바꿀 때만 올립니다(추가는 올리지 않음).
- `input.schema`는 **읽은 파일의 실제 schema**(1~4)입니다(6절 6번). `examples`처럼 입력 파일이 없으면 `"input": null`.
  (v4) `bound`는 `null`, `build`는 `{"path": <명세 경로>, "spec_version": 1}`, `journal`은 `{"path": <기록 폴더>}`.
- **직렬화**: `cli/output.py`의 정리 함수가 페이로드를 재귀로 돌며 바꾼 뒤 `json.dumps(..., allow_nan=False)`로 씁니다.
  - 유한하지 않은 `float`·`np.floating` → `null` (`json`은 float를 `default`보다 먼저 처리하므로 `default`만으로는 막을 수 없음)
  - `np.integer` → `int`, `np.bool_` → `bool`, `tuple` → `list`, `np.ndarray` → 중첩 리스트(유한하지 않은 원소는 `null`)
  - 복소수는 출력하지 않습니다(필요하면 `{"re", "im"}`로 명시 변환).
  - 진행 JSONL(4.2절)에도 같은 정리 함수를 씁니다.
- 숫자는 **SI 단위, 키 이름에 단위를 붙입니다**: `f_hz`, `thickness_m`, `mass_kg_m2`, `rl_db`, `theta_deg`.
  GUI 표시 단위(GHz, mm)는 CSV에서만 씁니다(GUI 내보내기와 같은 형식).
- **파라미터 값은 SI로**: `get_param()`과 `OptimizationResult.values`는 SI(m, Hz, H, F, kg/m³)인데
  `param_unit()`은 표시 단위(`mm`, `GHz`, `nH`, `pF`, `g/cm3`)를 돌려줍니다. 둘을 그대로 짝지으면 10³~10¹²배 틀린 값이 됩니다.
  그래서 파라미터마다 `{"value": <SI>, "unit": "<SI 단위>", "display_unit": "mm", "display_value": <표시 값>}`을 씁니다.
  환산표는 6절 5번에서 엔진으로 옮깁니다.
- **RL 부호는 내부 규약**(20·log₁₀|Γ|, 음수가 좋음)으로 고정합니다. 키 이름이 `rl_db`이고 `--help`에 명시합니다.
- 경로 튜플은 JSON 배열로 씁니다: `["layer", "<uid>", "thickness"]`. 사람이 읽을 라벨(`describe_path`)을 함께 붙입니다.

### 4.2 stderr: 진행 상황 (JSONL)
- `--progress`를 주면 장시간 명령(`optimize`, `tolerance`)이 stderr에 **한 줄에 JSON 하나**씩 씁니다.
  ```json
  {"event": "progress", "command": "optimize", "stage": "global", "combo": 1, "n_combos": 4, "iteration": 12, "best": 0.83, "n_evals": 1530, "elapsed_s": 4.2}
  {"event": "progress", "command": "tolerance", "done": 120, "total": 500, "elapsed_s": 3.1}
  ```
- `info["history"]`는 매번 전체 이력이라 **보내지 않습니다**(줄이 계속 커짐). 최종 결과에만 넣습니다.
- 엔진이 마지막에 보내는 `stage == "done"` 콜백(`optimizer.py:362`, docstring에는 없음)은 진행 줄로 내보내지 않습니다.
- 출력 간격은 `--progress-interval`(기본 1초)이며 CLI가 직접 조절합니다. 엔진 콜백 주기와는 무관합니다(5절).
- `--progress`가 없으면 stderr에는 경고·예외 외에 아무것도 쓰지 않습니다.

### 4.3 종료 코드
| 코드 | 뜻 | stdout |
|---|---|---|
| 0 | 성공 | `ok:true` 결과 봉투 |
| 1 | 예상하지 못한 내부 오류(버그) | `ok:false`, `code: internal_error`, traceback 일부 |
| 2 | 사용법 오류(인자) | `ok:false`, `code: usage` |
| 3 | 입력·출력 오류: 파일 없음, 읽을 수 없는 파일, 손상된 `.coat`, 더 새 schema, 없는 예제, 출력 파일이 이미 있음, 쓸 수 없음 | `ok:false` |
| 4 | 모델 오류: 계산 불가, 최적화 설정 무효, `check`가 오류 수준 이슈를 찾음, `--strict`에서 경고 | `ok:false` |
| 5 | 중단됨(시간 제한·Ctrl-C) — **부분 결과 있음** | `ok:true`, `stopped:true`, 그때까지의 최선 결과 |
| 130 | 두 번째 Ctrl-C로 강제 종료 | `ok:false`, `code: interrupted` (가능한 경우) |

### 4.4 내보내기 (`--format`, `--output`)
- `--format json`(기본): 4.1절의 봉투.
- `--format csv`: `solve`와 `tolerance`만 지원합니다. **GUI `data_table()`과 같은 열 구성과 같은 행 포맷**(`.9g`/`.6g`)입니다.
  - `solve --sweep freq`: `f [GHz], <q> TE, <q> TM, <q> avg` (`--quantity RL|R|T|A`, 기본 RL) — `gui/plots/views.py:233`
  - `solve --sweep angle`: `theta [deg], …` — `views.py:300`
  - `solve --sweep map`: `f [GHz] \ theta [deg], <각도들…>` (`--pol`, 기본 avg) — `views.py:375`
  - `tolerance`: `f [GHz], nominal [dB], median [dB], lower [dB], upper [dB]` — `gui/panels/tolerance.py:82`
  - CLI CSV는 내부 RL 부호를 씁니다(GUI의 "RL 양수 표시" 설정은 CLI에 없음).
  - CSV를 `--output` 파일에 쓰면 stdout에는 봉투(`result.output_path`, 행 수)만 씁니다.
    `--output` 없이 CSV를 고르면 CSV 본문을 stdout에 씁니다(파이프용, 이때만 JSON 봉투 없음).
- `optimize --output OUT.coat`: 결과를 적용한 프로젝트를 저장합니다. **입력 파일 덮어쓰기는 `--in-place`를 줄 때만** 합니다.
- 기존 파일을 덮어쓰려면 `--force`가 필요합니다. 없으면 `file_exists`(종료 3). 출력 쓰기에서 `OSError`가 나면 `file_unwritable`(종료 3).

### 4.5 오류 코드 표
엔진 예외에는 안정된 코드가 없으므로 **CLI가 예외 종류 → 코드**로 바꿉니다. 엔진 메시지는 `message`에 그대로 둡니다.
`SolverError`·`OutOfRangeError`·`MaterialCycleError`·`ProjectError`·`OptimizationError`가 모두 `ValueError`의 하위 클래스이므로
**하위 클래스부터 순서대로** 검사하고, 일반 `ValueError`는 맨 마지막에 둡니다.

**파일 읽기 단계**(`Project.load` 주변, 6절 6번)

| 예외 | 코드 | 종료 |
|---|---|---|
| `FileNotFoundError` | `file_not_found` | 3 |
| `IsADirectoryError`, `PermissionError`, 그 밖의 `OSError` | `file_unreadable` | 3 |
| `NewerSchemaError` (6절 6번) | `newer_schema` (`details.schema`, `details.supported`) | 3 |
| `ProjectError`, `UnicodeDecodeError`, `ValueError`, `KeyError`, `TypeError`, `AttributeError` | `invalid_project` | 3 |

**계산 단계**

| 예외 | 코드 | 종료 |
|---|---|---|
| `OutOfRangeError` | `material_out_of_range` (`details`: `material`, `data_lo_hz`, `data_hi_hz`, `req_lo_hz`, `req_hi_hz`) | 4 |
| `MaterialCycleError` | `material_cycle` | 4 |
| `SolverError` | `solver_error` | 4 |
| `OptimizationError` | `invalid_optimization_settings` | 4 |
| `KeyError` (없는 재료·층 등) | `unknown_reference` | 4 |
| `ValueError` (위에 해당 없음) | `invalid_value` | 4 |
| 그 밖의 `Exception` | `internal_error` | 1 |

**CLI 자체**: `usage`(2), `unknown_example`(3), `file_exists`(3), `file_unwritable`(3), `validation_failed`(4, `check`),
`preflight_warnings`(4, `--strict`), `no_valid_design`(4, `optimize`), `interrupted`(130).

재료 진단은 기존 `Issue.code`(`out_of_range`, `eps_gain`, `snoek`, `demo_values` …)를 그대로 쓰고,
새로 `material_cycle`, `unknown_material`을 더합니다(6절 3번).

### 4.6 언어
CLI는 `tr()`을 쓰지 않고 영어로만 출력합니다. 재료 진단 문장은 `issue_text(iss, lang="en")`로 만듭니다.
`i18n._lang`을 바꾸지 않으므로 같은 프로세스의 다른 코드에 영향이 없습니다. `i18n.py`는 Qt를 지연 import하므로
(`detect_system_language` 안에서만) CLI import 경로에 Qt가 들어오지 않습니다 — 9절 1번 테스트로 확인합니다.

## 5. 장시간 작업: 진행·중단·시간 제한

- 중단 신호는 `threading.Event` 하나로 모읍니다. 다음 세 가지가 이 이벤트를 세웁니다.
  1. **SIGINT(Ctrl-C)**: 처리기가 이벤트만 세웁니다. `KeyboardInterrupt`가 SciPy 안에서 터지지 않게 하려는 것입니다.
     두 번째 Ctrl-C는 기본 처리기로 되돌려 즉시 끝냅니다. 이때 생기는 `KeyboardInterrupt`(`BaseException`)는 `main()`이 잡아
     `interrupted` 봉투와 종료 코드 130을 씁니다(`solve`처럼 콜백이 없는 명령에서 Ctrl-C가 나도 같음).
  2. **SIGTERM**: POSIX에서만 같은 처리를 합니다(Windows는 지원 범위 밖).
  3. **`--timeout SEC`**: 콜백에서 경과 시간을 비교합니다.
- **신호 처리기는 `main()` 안에서 설치하고 `finally`에서 원래 처리기로 되돌립니다.** 메인 스레드일 때만 설치합니다
  (`threading.current_thread() is threading.main_thread()`). 테스트에서 `main(argv)`을 프로세스 안에서 불러도 pytest의 처리기를 덮어쓰지 않게 하려는 것입니다.
- 엔진 콜백은 이벤트가 서 있으면 True를 반환합니다 → 엔진이 최선 결과와 `stopped=True`를 돌려줍니다 → 종료 코드 5.
- **최적화: `throttle_s=0.0`으로 부릅니다.** `optimize()`의 `emit()`은 `throttle_s` 안에서는 콜백을 아예 부르지 않으므로
  (`optimizer.py:256-268`), 0이 아니면 그 사이의 중단 요청과 시간 제한이 무시됩니다(빠른 문제에서는 실행 전체가 이 창 안에 들어감).
  0으로 두면 DE 세대마다, L-BFGS-B 반복마다 확인합니다. 진행 출력 빈도는 CLI가 `--progress-interval`로 따로 줄입니다.
  기존 테스트도 `throttle_s=0.0`을 씁니다(`tests/test_optimize_tolerance.py:55`).
  DE 콜백은 세대가 끝날 때만 불리므로 한 세대가 긴 문제에서는 중단까지 그만큼 늦어질 수 있습니다(`--help`에 적음).
- **공차 분석: 마지막 표본에서는 중단하지 않습니다.** `run_tolerance`는 표본을 추가한 **뒤에** `progress(k+1, n)`을 부르므로
  (`tolerance.py:89-95`), `k+1 == n`에서 True를 돌려주면 표본을 다 계산하고도 `stopped=True`가 됩니다. CLI 콜백은 `done == total`이면 False를 반환합니다.
  부분 결과는 이미 계산한 표본으로 밴드·수율을 냅니다(`n_samples`에 실제 수).

## 6. 엔진 쪽 리팩터링 (Qt 없음)

CLI와 GUI가 같은 숫자를 내도록 GUI 안에 있던 로직을 엔진으로 옮기고, 리뷰에서 나온 엔진 결함을 고칩니다.
1·2·4·5번은 **위치만 옮기고 동작은 바꾸지 않습니다.** 3·6·7번은 작은 동작 변경이며 각각 테스트를 붙입니다.

1. **`yield_intervals(p)`, `yield_band(p)`** — `gui/panels/tolerance.py:25` → `tolerance.py`.
   GUI는 새 위치에서 import합니다(GUI 모듈에서 같은 이름을 다시 내보내 기존 import 호환 유지).
2. **공차 분석 주파수 격자** — GUI의 `min(sw.n_f, 301)` 규칙(`gui/panels/tolerance.py:351`)을
   `tolerance.tolerance_frequencies(p)`로 옮깁니다. 본문은 `p.sweep.freq_grid(min(p.sweep.n_f, 301))`이고 GUI 식과 같은 값입니다.
3. **최적화 사전 점검** — `gui/panels/optimization.py:544 _preflight`의 판정 부분을
   `optimize.optimizer.preflight(project, settings) -> (errors: list[Issue], warnings: list[Issue])`로 옮깁니다. GUI는 대화상자만 남깁니다.
   - `validate_settings()`가 내는 `OptimizationError`는 그대로 위로 던집니다(CLI는 `invalid_optimization_settings`).
   - `validate_settings()`의 `project.structure.layer_by_uid(c.uid)`(`optimizer.py:230`)가 날것의 `KeyError`를 내는 것을 고쳐
     `OptimizationError(f"choice layer {c.uid!r} no longer exists")`로 바꿉니다(변수 쪽 220-223행과 같은 처리). GUI의 `KeyError` 처리는 남겨 둡니다.
   - 없는 재료는 `Issue("error", "unknown_material", name, {"n": name})`. `_ISSUES_EN["unknown_material"] = "Unknown material: {n}"`로 두면
     **KO 항목이 이미 있으므로**(`i18n_ko.py:227`) 새 번역이 필요 없고, GUI 문구도 지금과 같습니다.
4. **RL 변환** — 새 메서드를 만들지 않고 이미 있는 `core.units.power_to_db`(`units.py:48`, 같은 `10·log10(max(p, 1e-30))`)를 씁니다.
   CLI는 `power_to_db(res.quantity("R", pol))`. `res`는 `(Nf, Na)` 2차원이므로 주파수 스윕은 `[:, 0]`, 각도 스윕은 `[0, :]`로 자릅니다.
   GUI의 같은 식(`views.quantity_values`, `MainWindow._update_summary`, `tolerance.rl_db`)은 이번에 건드리지 않습니다(값이 같으므로 필요 없음).
5. **단위 환산표** — `gui/fmt.py`의 `_SCALE`(표시 단위 → SI 배율)을 `core/units.py`로 옮기고 `SI_UNIT`(`mm→m`, `GHz→Hz`, `nH→H`, `pF→F`,
   `g/cm3→kg/m3`, `ohm`, `S/m`, `frac`, `""`)을 더합니다. `gui/fmt.py`는 새 위치를 import합니다. CLI는 4.1절의 파라미터 표기에 씁니다.
6. **`.coat` 읽기 오류 정리** — `project.py`:
   - `class NewerSchemaError(ProjectError)`를 추가하고 `from_dict`의 schema 검사(`project.py:416`)에서 씁니다(`schema`, `supported` 속성). GUI 동작은 같습니다(`ProjectError`로 잡힘).
   - `from_dict`가 읽은 schema를 `project.source_schema`에 남깁니다(직렬화하지 않는 속성, `copy()`·새 프로젝트에서는 `SCHEMA_VERSION`).
   - `load()`의 예외 처리는 그대로 두고, 넓은 예외 묶음은 CLI 쪽(4.5절)에서 잡습니다. GUI `load_path`(`main_window.py:517`)와 같은 방식입니다.
7. **`check_material`의 순환 참조** — `checks.py:60`에서 `MaterialCycleError`도 잡아 `Issue("error", "material_cycle", name, {})`를 돌려줍니다.
   `_ISSUES_EN["material_cycle"]` 문구가 새로 생기므로 **KO 항목도 추가**합니다(i18n 규칙). 지금은 순환 혼합물이 있으면 GUI 진단 갱신에서 예외가 납니다 — 같은 수정으로 GUI도 고쳐집니다.
8. **모델 예외 묶음** — `(SolverError, OutOfRangeError, MaterialCycleError, KeyError, ValueError)`를 상수로 두는 일은 **`core/solver.py`에 두지 않습니다.**
   `materials/models.py:18`이 `core.constants`를 import하면서 `core/__init__.py` → `core/solver.py`가 실행되므로, solver가 `materials.models`를 import하면
   `materials`를 먼저 import하는 코드에서 순환 import로 깨집니다(또 `core/`는 지금 `materials/`를 import하지 않음). CLI는 4.5절의 표를 `cli/output.py`에 직접 둡니다.

## 7. 명령별 상세

공통 옵션: `--format`, `--output`, `--force`, `--progress`, `--progress-interval`, `--timeout`, `--quiet-warnings`(info 수준 진단 생략).
`--seed`는 음수를 `None`(무작위)으로 바꿉니다 — GUI 규약(`gui/panels/optimization.py:500`, `gui/panels/tolerance.py:303`)과 같고,
음수를 그대로 넘기면 `np.random.default_rng`가 `ValueError`를 냅니다.
(v4) **시드가 `None`(무작위)이면 CLI가 `secrets.randbelow(2**31)`로 정수 시드를 정해 엔진에 넘기고, 결과와 실험 기록에 `seed_used`로 남깁니다.**
`optimize`·`tolerance` 모두 해당합니다. 그래야 기록된 시도를 그대로 재현할 수 있습니다.

### `coating-cli examples [list | save KEY -o PATH]`
- `list`: `[{"key": "salisbury", "name": "Salisbury screen", "description": "..."}, …]`.
  `description`은 `p.notes`가 비어 있으면 빌더 함수의 docstring을 씁니다(예제 7개 중 4개는 `notes`가 비어 있음).
- `save`: 예제 프로젝트를 `.coat`로 저장. 결과에 경로와 층 수. 없는 키는 `unknown_example`(종료 3). `"input": null`.

### `coating-cli info FILE`
- `result`: `name`, `notes`, `incident`, `backing`, `layers[]`(`index`, `uid`, `kind: slab|sheet`, `name`, `material`, `thickness_m`, 시트면 `model`과 SI 값),
  `materials[]`(`name`, `kind`(=`Material.kind`), `users`(=`material_users(name)`, 혼합물 성분·최적화 후보 포함), `used`),
  `total_thickness_m`, `areal_mass_kg_m2`, `sweep`, `optimization`(targets, variables, choices, 가중치), `tolerance` 설정,
  `params[]`(`path`, `label`, 4.1절 형식의 값·단위).
- `areal_mass()`는 `(KeyError, MaterialCycleError)`를 잡아 `null`로 둡니다(`main_window.py:436-439`와 같음). 깨진 파일에서도 `info`는 동작해야 합니다.
- 에이전트가 경로 튜플을 직접 만들지 않고 여기서 복사해 쓰게 하는 것이 목적입니다.
- (v4) `optimization.n_combos`(재료 조합 수)와 `optimization.estimated_max_evals`를 냅니다. 조합이 64개 이하이면 조합마다 DE 전체를 돌리므로
  대략 `n_combos × (maxiter + 1) × popsize × n_vars`입니다(`optimizer.py:302-315`). `check`도 같은 값을 냅니다.

### `coating-cli check FILE`
- `result`: `{"valid": bool, "counts": {"error", "warning", "info"}, "issues": [...]}`. 이슈 출처는 다음 네 가지이고, **같은 이슈는 한 번만** 냅니다((v4) 중복 판정 키는 `(code, material, target index, message)`).
  1. `project.validate()` — 없는 재료 참조(`unknown_material`).
  2. **시험 계산** — GUI `recompute`처럼 주파수 스윕 격자로 `solve`를 한 번 돌려, 실패하면 4.5절 코드로 `solver_error` 등의 이슈를 만듭니다
     (손실 있는 입사 매질, 음수 두께, 잘못된 RLC 값 등 `validate()`가 못 잡는 문제). GUI 진단 목록의 `result_error`에 해당합니다.
  3. 재료 진단 — 사용 중인 재료(층 + 후보)와 **혼합물이 참조하는 성분까지 펼쳐서** `check_material`. 주파수는 GUI 진단과 같게 `freq_grid(min(n_f, 200))`.
     (GUI 진단은 지금 직접 쓰는 재료만 보므로, 성분까지 보는 것은 CLI가 더 넓습니다. GUI에 같은 확장을 적용하는 일은 미룹니다.)
  4. 최적화 사전 점검 — **변수나 재료 선택이 있을 때만**(`p.optimization.variables or choices`). 모든 프로젝트에 기본 목표(8-12 GHz)가 있고
     변수는 비어 있으므로, 무조건 돌리면 모든 파일이 "no optimisation variables selected"로 실패합니다. `--no-opt`로 끌 수 있습니다.
- 오류 수준 이슈가 하나라도 있으면 `ok:false`, `error.code = "validation_failed"`, 종료 코드 4. `result`는 그대로 함께 씁니다(4.1절 불변식).

### `coating-cli solve FILE [--sweep freq|angle|map] [--quantity RL|R|T|A] [--pol TE|TM|avg] [--targets]`
- 기본 격자는 프로젝트 `sweep` 설정 그대로이며 GUI `recompute`(`main_window.py:420-423`)와 같습니다.
  - `freq`: `freq_grid(n_f)` × `angle`
  - `angle`: `f_at` × `angle_grid()`
  - `map`: `freq_grid(map_n_f)` × `angle_grid(map_n_angle)` (주파수 스윕 점 수가 아님)
- 덮어쓰기 옵션(사람이 치기 쉽게 GHz로 받되 이름에 단위 명시): `--f-min-ghz`, `--f-max-ghz`, `--n-f`, `--log-f/--linear-f`, `--angle-deg`, `--f-at-ghz`,
  `--angle-min-deg`, `--angle-max-deg`, `--n-angle`, `--map-n-f`, `--map-n-angle`.
  (개발 이력 3.23) 점 간격은 `--log-f`(로그) / `--linear-f`(주파수 등간격) / `--linear-wavelength`(진공 파장 등간격) 중 하나로, 서로 함께 쓸 수 없고
  각각 파일의 간격 설정을 대신합니다. 파장 등간격 격자도 주파수 오름차순이고 양 끝은 정확히 f_min·f_max입니다.
- `--touchstone PATH`(주파수 스윕만): S11을 Touchstone `.s1p`로 함께 씁니다. 파일 하나에 편광 하나이므로 `--pol TE|TM`을 쓰고, `avg`는 수직 입사에서만
  받습니다(TE로 씀). 기준 저항 R은 입사 매질의 모드 파동 임피던스(TE η/cosθ, TM η·cosθ)입니다. 결과에 `touchstone_path`, `touchstone_pol`,
  `touchstone_ref_ohm`이 붙습니다. 기존 파일은 `--force` 없이는 덮어쓰지 않습니다.
- JSON `result`:
  - `summary`: 편광 `TE`·`TM`·`avg` 각각의 `best_rl_db`, `best_f_hz`(각도 스윕이면 `best_theta_deg`), `total_thickness_m`, `areal_mass_kg_m2`.
  - `--targets`일 때만 목표별 `worst_rl_db`, `margin_db`(`evaluate_terms` 재사용). `evaluate_terms`는 스윕 격자가 아니라 목표 격자로 따로 계산하고,
    기본 목표가 모든 프로젝트에 있으므로 기본으로는 넣지 않습니다. 목표 계산이 실패하면(예: 측정 범위 밖) 그 부분만 `null` + 경고로 둡니다.
  - `data`(열 지향):
    - `freq`: `f_hz`(1차원), `theta_deg`(스칼라), `rl_db`/`R`/`T`/`A` 각각 `{"TE": [...], "TM": [...], "avg": [...]}` (`[:, 0]`)
    - `angle`: `f_hz`(스칼라), `theta_deg`(1차원), 같은 구조 (`[0, :]`)
    - `map`: `f_hz`(1차원), `theta_deg`(1차원), `rl_db[pol]` 2차원(`Nf × Na`)
    - `--layer-absorption`이면 층별 흡수(`layer_uids` 순서)
- `--summary-only`: `data`를 뺍니다(에이전트가 큰 배열을 읽지 않고 판단할 때).

### `coating-cli optimize FILE [-o OUT.coat | --in-place] [--seed N] [--maxiter N] [--popsize N] [--no-polish] [--strict]`
- 시작 전에 `preflight`를 돌립니다. 오류면 종료 코드 4. 경고(`level == "warning"`)가 있으면 GUI는 "그래도 실행?"을 묻지만
  CLI는 **기본적으로 실행하고 경고를 `warnings`에 담습니다**(에이전트는 대화상자에 답할 수 없음). `--strict`면 경고에서 멈춥니다(`preflight_warnings`, 종료 4).
  `info` 수준(`demo_values`)은 `--strict`에서도 멈추지 않습니다(GUI `_preflight`와 같음).
- 옵션 값은 프로젝트 사본의 `optimization` 설정만 바꿉니다(입력 파일은 그대로).
- 엔진 호출은 `optimize(p, s, progress=cb, throttle_s=0.0)`(5절).
- (v5) **`--restarts N`**(기본 1): 시드 `seed_used, seed_used+1, …`로 N번 돌려 목적함수가 가장 작은 결과를 냅니다. 결과에 시작별 `seed`·`objective`·`margin_db`를 남깁니다.
  모의 실행에서 같은 구조라도 시드에 따라 margin이 +5.7 dB와 +6.9 dB로 갈렸고, 3층 구조가 국소 최적에 빠져 2층보다 나빴습니다(12.5절).
  중단·시간 제한은 전체 재시작에 걸쳐 적용되고, 그때까지 끝난 시작 중 최선을 냅니다.
- `result`: `message`, `n_evals`, `elapsed_s`(=`res.elapsed`), `terms`(`res.terms.as_dict()`, `res.terms`가 `None`이면 `null`),
  `values[]`(`path`, `label`, `before`, `after` — 4.1절 형식), `choices[]`(`uid`, `layer`, `before`, `after`), `history`(`[[n_evals, best], …]`), `output_path`.
  `before`는 `apply_result()`를 부르기 **전에** 기록합니다.
- 유효한 설계를 못 찾으면(`terms is None`, `message == "no valid design found"`) `ok:false`, `solver_error`류가 아니라 `no_valid_design`(종료 4), 파일은 쓰지 않습니다.
  (N2 결정) `error.details.first_failure`에 처음 실패한 평가의 원인(4.5절 코드와 메시지, 예: `material_out_of_range`)을 담아, 에이전트가 모델의 어디를 고칠지 알 수 있게 합니다.
- 중단(5절)이면 `stopped: true`, 종료 코드 5. `-o`가 있으면 부분 결과도 저장합니다(결과에 `stopped`를 적어 구분).

### `coating-cli tolerance FILE [--seed N] [--n-samples N] [--target-db G] [--angle-deg X] [--pol TE|TM|avg] [--samples]`
- 격자는 `tolerance_frequencies(p)`, 수율 기준 대역은 `yield_intervals(p)` (GUI와 같음).
- `result`: `n_samples`, `yield_fraction`, `target_db`, `lower_pct`, `upper_pct`, `yield_intervals_hz`, `worst_db`의 통계(`min`, `median`, `max`),
  `data`(같은 길이의 1차원 배열만: `f_hz`, `nominal_db`, `median_db`, `lower_db`, `upper_db`). `--summary-only` 지원.
- 표본별 `worst_db` 전체는 `--samples`일 때만 넣습니다.
- (v5) **`--corners`**: 활성 목표마다 (각도 범위의 양 끝) × (목표 편광)을 각각 평가합니다(13.7절). 결과에 꼭짓점별 수율과 **결합 수율**을 냅니다.
  `--corners` 없이 실행하면 GUI와 같은 단일 각도·편광 계산이고, 결과에 `scope: {"angle_deg", "pol"}`과 "단일 각도 기준" 경고를 항상 붙입니다.
- (3.19) **`--angle-grid [--n-angle N]`**: `--corners`와 같되, 각도 범위가 있는 목표는 그 목표의 각도 격자(`n_angle`점, `--n-angle`로 덮어씀, N ≥ 2)를 평가합니다.
  `n_angle`이 2 미만이면 양 끝을 평가하고 경고 `angle_grid_fallback`을 붙입니다. `--corners`와 `--angle-grid`는 함께 쓸 수 없고,
  둘 다 `--angle-deg`·`--pol`과 함께 쓰면 사용 오류(종료 2)입니다. `-o`는 JSON 결과 전체를 파일에 쓰고 봉투에는 요약만 둡니다(단일 각도 모드도 같음).
  `--format csv`는 가장 취약한 행의 곡선입니다(GUI 데이터 내보내기와 같음). 진행 이벤트는 표본 단위 `done`/`total`입니다.
- (v4) `--target-db`는 수율 기준(`ToleranceSettings.target_db`, 기본 −10 dB)을 덮어씁니다. 최적화 목표(기본 −20 dB)와 다를 수 있으므로 결과에 `target_db`를 항상 적습니다.

## 8. 코드 구성

```
src/coating_studio/cli/
  __init__.py      # main(argv=None) -> int
  __main__.py      # raise SystemExit(main())
  output.py        # 봉투, 정리 함수(NaN→null, numpy→Python), 오류 코드 표, 종료 코드
  progress.py      # 중단 이벤트, 신호 처리기 설치/복원, 시간 제한, stderr JSONL
  commands.py      # 하위 명령 구현 (엔진 호출 + 결과 dict 조립)
  spec.py          # (v3) 설계 명세 ↔ Project 변환, 단위 접미사 처리
  journal.py       # (v3) 실험 기록 쓰기·요약
```
- (v3) **`commands.py`의 각 명령은 순수 함수**로 둡니다: 입력은 `Project`(또는 경로)와 옵션 dict, 중단 이벤트, 진행 콜백이고,
  출력은 결과 dict 또는 예외입니다. argparse, stdout, 신호 처리, 종료 코드는 `__init__.py`·`output.py`·`progress.py`에만 둡니다.
  이렇게 하면 나중의 MCP 어댑터(13.6절)나 Python에서 직접 부르는 경우가 같은 함수를 재사용합니다.
- (v3) Rozanov 계산은 엔진 쪽 새 모듈 `src/coating_studio/limits.py`(Qt 없음)에 둡니다. GUI에서도 나중에 쓸 수 있게 하기 위해서입니다.
- argparse만 씁니다(새 의존성 없음).
  - `ArgumentParser.error`를 덮어써서 `_UsageError`를 던지고, `main()`이 잡아 `usage` 봉투 + 종료 코드 2를 씁니다.
  - `--help`는 argparse가 `SystemExit(0)`을 던지므로 `main()`이 `SystemExit`을 잡아 그 코드를 반환합니다(출력은 일반 텍스트).
- `main(argv)`은 `sys.exit`을 부르지 않고 종료 코드를 반환합니다(테스트에서 프로세스 안에서 부르기 위해). `KeyboardInterrupt`도 잡습니다(5절).
- `pyproject.toml`: `[project.scripts] coating-cli = "coating_studio.cli:main"`.
- `cli/`는 `gui/`와 matplotlib을 import하지 않습니다.

## 9. 테스트 (`tests/test_cli.py`)

1. **Qt 경계**: subprocess로 `python -c "from coating_studio.cli import main; main([...]); import sys; assert 'PySide6' not in sys.modules and 'matplotlib' not in sys.modules"`를
   `examples`·`info`·`check`·`solve`·`optimize`·`tolerance`·(v4) `build`·`spec`·`bound`·`journal` 각각 실행.
2. **GUI와 같은 숫자** (허용 오차 없이 정확히 같음):
   - `solve` freq/angle/map 결과가 직접 부른 `solve(...)` + `power_to_db`와 같음. map 격자 크기가 `map_n_f × map_n_angle`.
   - Salisbury 예제: f₀에서 수직 입사 |Γ| ≈ 0 (기존 해석해 테스트와 같은 기준).
   - `tolerance`: 같은 시드로 `run_tolerance(p, tolerance_frequencies(p), band=yield_intervals(p))`와 수율·밴드가 같음.
     `tolerance_frequencies`가 옮기기 전 GUI 식과 같은 배열을 내는지도 확인.
   - `optimize`: 작은 `maxiter`로 같은 시드 → 직접 부른 `optimize()`와 `terms`가 같음.
3. **봉투 규약**: 모든 명령의 stdout이 `json.loads` 한 번으로 파싱됨, `ok`·`command`·`cli_schema` 존재, `ok == (exit in (0, 5))`.
   정리 함수 단위 테스트: `nan`, `inf`, `np.float64(nan)`, `np.int64`, `np.bool_`, 튜플, 2차원 ndarray(NaN 포함).
   `optimize`의 `margin_db = nan`, 진행 줄의 `best = inf`가 `null`이 되는지.
4. **파라미터 단위**: `info`의 두께 파라미터가 `value`(m)·`unit: "m"`·`display_value`(mm)·`display_unit: "mm"`로 서로 맞음. 시트 L(nH↔H), 재료 f0(GHz↔Hz)도.
5. **오류 경로**: 파일 없음(3), 디렉터리(3), JSON 아님(3), UTF-8 아닌 이진 파일(3), 루트가 배열인 JSON(3), 다른 앱 파일(3),
   필드가 깨진 `.coat`(3, `invalid_project`), 더 새 schema(3, `newer_schema`), 측정 범위 밖 Tabulated 재료(4, details 키 확인),
   순환 혼합물(`solve` 4 / `check`의 `material_cycle` 이슈), 변수 없는 최적화(4), 없는 선택 층 uid(4, `invalid_optimization_settings`),
   잘못된 인자(2, JSON 봉투), `--help`(0, `main()`이 int 반환), 기존 출력 파일 + `--force` 없음(3, `file_exists`), 없는 예제(3).
6. **`check`**: 변수 없는 기본 프로젝트가 `valid: true`(종료 0). 혼합물 성분의 경고가 잡힘. 손실 있는 입사 매질이 시험 계산 이슈로 잡힘. 같은 이슈가 중복되지 않음(목표가 여럿인 `rozanov_*`는 각각 남음).
7. **중단**: 테스트용 훅으로 이벤트를 직접 세워 `optimize`·`tolerance`가 `stopped:true` + 종료 코드 5 + 유효한 부분 결과.
   `--timeout`이 짧은 문제에서도 실제로 멈춤(`throttle_s=0.0` 확인). 공차 분석이 마지막 표본에서 시간 제한에 걸려도 `stopped:false`.
   in-process `main()` 뒤 SIGINT 처리기가 원래대로 돌아와 있음. (실제 SIGINT를 보내는 테스트는 POSIX에서만, Windows는 skip)
8. **진행 출력**: `--progress`일 때 stderr 각 줄이 JSON이고 `history` 키가 없으며 `stage: done` 줄이 없음.
9. **내보내기**: `solve --format csv`의 헤더와 행이 GUI `data_table()` 포맷과 같음(오프스크린 GUI 없이 같은 포맷 함수 비교).
   `optimize -o`로 저장한 파일을 다시 로드하면 `values`가 반영돼 있음.
10. **`--seed -1`**: `optimize`·`tolerance` 모두 오류 없이 동작.
10a. (v5) `tolerance --corners`: 꼭짓점마다 `run_tolerance`를 직접 부른 결과와 같고, 결합 수율이 꼭짓점별 최소 수율 이하. 꼭짓점 사이 표본이 같은 섭동인지(같은 시드) 확인.
     (3.19) `--angle-grid`도 행마다 `run_tolerance`와 비트 단위로 같고, 2점 격자는 꼭짓점 결과와 같음. 쓸 수 없는 옵션 조합은 사용 오류.
10b. (v5) `optimize --restarts 3`: 시작별 결과가 `--seed`를 각각 준 단일 실행과 같고, 최선이 선택됨.
10c. (v5) `mixture_fraction_range` 이슈: Bruggeman 전도성 충전재 분율 0.30 근처, MG 분율 0.35에서 경고, 변수 범위가 위험 구간을 포함해도 경고.
10d. (v5) `materials`의 재료 dict를 그대로 명세에 넣어 `build`하면 내장 재료와 같은 `to_dict()`.
10e. (v6) 측정 재료: 목표가 측정 범위 밖이면 `invalid_spec`, sweep 생략 시 `sweep_clamped`로 측정 범위 안에 들어감, 명시한 sweep이 밖이면 `invalid_spec`.
10f. (v6) `fraction_wt`: 알려진 밀도로 손계산한 부피 분율과 같음, `unit: "wt"` 범위 변환, `value_wt` 출력.
10g. (v6) `fit`: 알려진 Debye 재료에서 만든 합성 CSV를 맞추면 계수가 복원되고 잔차가 작음(`fitting.py` 기존 테스트와 같은 기준).
10h. (v6) Rozanov: 0–30° 목표에서 수직 입사로 불가능한 설계가 `infeasible`(v5에서는 `unknown`이었음). 30–60° 목표는 `unknown`.
10i. (v6) 부록 B의 모든 예시 JSON이 실제 출력과 키 구조가 같음(예시를 테스트 픽스처로 삼아 키 집합 비교).
11. **리팩터링 회귀**: 기존 `test_optimize_tolerance.py`, `test_gui_smoke.py`, `test_i18n.py` 그대로 통과. `preflight`가 GUI 대화상자와 같은 오류·경고 목록을 냄.
    새 `_ISSUES_EN` 문구(`material_cycle`)의 KO 항목 존재.

게이트: `QT_QPA_PLATFORM=offscreen python -m pytest` (CI 3 OS × Python 3.10/3.13).

## 10. 커밋 계획

1. **엔진 리팩터링·수정** (6절): 옮긴 함수, `preflight`, `NewerSchemaError`·`source_schema`, `check_material` 순환 처리, `validate_settings`의 `KeyError`,
   단위 환산표, i18n 문구(+KO). GUI는 새 위치를 import. 엔진 단위 테스트 추가. 기존 테스트 통과.
2. **CLI 추가** (`cli/`, `pyproject.toml`, `tests/test_cli.py`) — 1~7절의 명령.
3. (v3) **에이전트 실험 루프** — `limits.py`(+단위 테스트), `cli/spec.py`·`build`·`spec`, `cli/journal.py`·`--journal`·`journal`, `bound`, `check`의 `limits`,
   (v5) `materials`, `tolerance --corners`, `optimize --restarts`, `mixture_fraction_range` 이슈(+KO),
   (v6) `fit`, `fraction_wt`, 측정 범위 검사(`sweep_clamped`, `sweep_outside_data` +KO), `spec -o`, 부록 B 키 구조 테스트.
4. (v4) **플레이북과 연결** — `docs/AGENT_PLAYBOOK.md`, `.claude/skills/coating-experiment/SKILL.md`, `AGENTS.md` 단락(13.6절). MCP 코드는 넣지 않음.
5. **문서**: README(영·한)에 CLI 절, AGENTS.md "Commands"에 `coating-cli` 추가, `DEVELOPMENT_HISTORY.md`에 기록.

`.coat` 저장 형식은 바뀌지 않으므로 `SCHEMA_VERSION`은 올리지 않습니다(`source_schema`는 저장하지 않는 속성).
커밋 1에 GUI 화면 문구 변화는 없습니다(`unknown_material`은 기존 문구와 같고, `material_cycle`은 지금까지 예외로 나던 경우에만 보임).
그래도 2.1절 6단계에 따라 영문·한글 진단 패널을 오프스크린으로 한 번 캡처해 확인합니다.

## 11. 열린 질문

모든 열린 질문을 결정했습니다. Q1~Q7은 12.2절, N3~N6은 12.4절, N1·N2·N7~N10은 12.7절에 근거와 함께 있습니다.
구현 중에 새 질문이 생기면 여기에 N11부터 이어 적습니다.

## 12. Argon 리뷰 반영 기록

리뷰: 2026-11-07, `gemini-4-argon-high`, `--mode plan`, 읽기 전용 권한(DEVELOPMENT_HISTORY 2.2절). 첫 실행에서 거부 없이 끝났습니다.
지적 14건의 근거 `파일:줄`을 모두 직접 열어 확인했습니다. **14건 모두 코드와 일치**했고, 2건은 고치는 방법을 다르게 정했습니다.

### 12.1 지적과 판정

| # | 심각도 | 지적 | 판정 | 반영 |
|---|---|---|---|---|
| 1 | blocker | `MODEL_ERRORS`를 `core/solver.py`에 두면 순환 import | 확인(`core/__init__.py:6`, `models.py:18`) | 6절 8번: 상수를 solver에 두지 않음 |
| 2 | blocker | `param_unit()`은 표시 단위, 값은 SI → 단위 불일치 | 확인(`project.py:476-485`) | 4.1절 파라미터 표기, 6절 5번 |
| 3 | blocker | `allow_nan=False`는 `default`보다 먼저 NaN에서 실패 | 확인(Python `json` 동작, `optimizer.py:58,252`) | 4.1절 정리 함수 |
| 4 | blocker | 변수 없는 프로젝트에서 `check`가 항상 실패 | 확인(`optimizer.py:197-198`, 기본 목표) | 7절 `check` 4번 조건부 |
| 5 | blocker | `check_material`이 순환 미처리, `validate_settings` 날것 `KeyError`, 성분 미검사, 계산 오류 누락, 중복 | 확인(`checks.py:60-67`, `optimizer.py:230`, `structure.py:149-156`) | 6절 3·7번, 7절 `check` |
| 6 | blocker | `Project.load`가 여러 예외를 그대로 냄 → 종료 1/4로 잘못 분류 | 확인(`project.py:431-440`, GUI `main_window.py:517`) | 4.5절 파일 읽기 단계 |
| 7 | major | `throttle_s=0.1`이면 중단·시간 제한이 무시됨 | 확인(`optimizer.py:256-268`). **v1의 내 설계가 틀렸음** | 5절 `throttle_s=0.0` |
| 8 | major | map 격자, `evaluate_terms` 부작용, angle/map 스키마 | 확인(`main_window.py:420-423`) | 7절 `solve`. 단 목표 평가는 Argon 안("변수가 있을 때만") 대신 **`--targets` 선택**으로 함 — 목표는 변수와 무관하게 의미가 있기 때문 |
| 9 | major | `--help`가 `SystemExit(0)` + 텍스트 | 확인 | 4.1·8절 |
| 10 | major | 신호 처리기 누수, `KeyboardInterrupt`, 마지막 표본 오판 | 확인(`tolerance.py:89-95`) | 5절 |
| 11 | major | `--seed -1`이 `default_rng`에서 실패, GUI는 -1=무작위 | 확인(`gui/panels/tolerance.py:303`, `optimization.py:500`) | 7절 공통 |
| 12 | major | 오류 코드 누락, `ValueError` 하위 클래스 순서, details가 GHz | 확인 | 4.5절 재작성 |
| 13 | minor | `input.schema`가 사라짐, `examples`는 입력 없음 | 확인(`project.py:413-425`) | 6절 6번 `source_schema`, 4.1절 |
| 14 | minor | `power_to_db` 이미 있음, 예제 notes 빈 것, `kind`, `material_users`, `res.elapsed`, `terms` None, `before` 시점, `lower_pct` 위치 | 확인(`units.py:48`, `models.py:48`, `project.py:276`) | 6절 4번, 7절 각 명령 |

### 12.2 열린 질문 결정 (v1 Q1~Q7)

| 질문 | 결정 | 근거 |
|---|---|---|
| Q1 `check` 오류 시 | `ok:false` + `validation_failed` + 종료 4, `result` 유지 | Argon 권고. `ok`만 보는 에이전트가 무효 모델을 통과로 보지 않게. 불변식 `ok == (exit in 0,5)` |
| Q2 사전 점검 경고 | 기본 진행 + `--strict` | 양쪽 일치. info 수준은 `--strict`에서도 무시 |
| Q3 `--set` | v1에서 뺌 | 경로 표현이 모호함. `.coat` 직접 수정으로 충분 |
| Q4 `unknown_material` | `Issue` 코드로, 기존 문구 `"Unknown material: {n}"` 재사용 | **KO 항목이 이미 있음**(`i18n_ko.py:227`, Argon이 찾음) → 새 번역 불필요 |
| Q5 PySide6 extra 분리 | 하지 않음 | 설치 명령·CI 호환성 |
| Q6 `--progress-file` | 뺌 | stderr JSONL로 충분 |
| Q7 JSON Schema | 뺌 | `cli_schema` + `--help` + README 예시로 충분 |

### 12.3 2차 리뷰(v3) 지적과 판정
리뷰: 2026-11-07, 같은 모델·같은 읽기 전용 권한. 첫 실행은 `--settings` 파일이 세션 임시 폴더에서 사라져 시작하지 못했고, 다시 만들어 실행했습니다(권한 거부 없음).
Argon은 코드를 실행할 수 없으므로, 실행으로만 확인되는 주장은 내장 예제 7개를 직접 돌려 대조했습니다.

| # | 심각도 | 지적 | 판정 | 반영 |
|---|---|---|---|---|
| 1 | blocker | 명세의 `angle_deg: [0, 30]`에 `n_angle`이 없으면 0°만 평가 | 확인(`project.py:102-110`, 기본 `n_angle=1`) | 13.2 목표 규칙 |
| 2 | blocker | 명세에 sweep·notes·최적화 설정·시트 모델·halfspace·층별 공차가 없어 왕복 불가 | 확인(실행: sweep 변경 5개, notes 3개, `maxiter=120` 2개, dualband `n_angle=4`·이름, cara RLC) | 13.2 전면 개정 |
| 3 | major | 단위 환산 오차로 왕복 비교 실패, 재료 dict의 SI 키와 접미사 규칙 충돌 | **일부 틀림**: 예로 든 `0.08e-12`는 실행해 보니 정확히 돌아옴. 일반 위험과 규칙 충돌은 맞음 | 13.2 `rtol` 비교, 재료 dict 예외 명시 |
| 4 | major | 내장 재료 생략 판정, 이름 없는 층의 왕복 | 확인(`is_builtin_demo(Air) == False` 실행 확인) | 13.2 `to_dict` 비교·`remove_builtin`, 층 이름 규칙 |
| 5 | blocker | Rozanov는 PEC 뒷판 전제, 입사 매질 파장 보정 | 확인(물리) | 13.4 적용 조건 |
| 6 | blocker | `rozanov_infeasible`을 오류로 두면 `check` 실패, 후보·재료 변수 무시, 상수 μ″의 정적 μ 과소평가 | 확인 | 13.4 경고 수준, `max_achievable_mu_d`, 해석적 `static_permeability` |
| 7 | major | 목표가 바뀐 시도끼리 margin 비교 불가, `solve`에 margin 없음 | 확인 | 13.3 `spec_fingerprint`, 기록 시 margin |
| 8 | major | `seed=None` 재현 불가, 재료 조합 수에 따른 실행 시간 폭증 | 확인(`project.py:143`, `optimizer.py:302-315`) | 7절 `seed_used`, `n_combos`·`estimated_max_evals`, 플레이북 |
| 9 | minor | `tolerance --target-db` 없음, `w_thickness` 주의, 명세 예시 재료, 새 명령의 envelope·테스트 누락, 중복 판정 키 | 확인 | 7·4.1·9절, 13.2 예시, 13.5 |

과다 범위 지적(필드당 단위 하나로 고정, MCP 코드 제외)도 받아들였습니다.

### 12.4 열린 질문 결정 (v3 N3~N6)

| 질문 | 결정 | 근거 |
|---|---|---|
| N3 연결 방식 | CLI + Skill/플레이북. MCP는 조건이 생기면 | 13.6절. Argon 권고와 제 잠정안이 일치 |
| N4 사입사 목표 | 수직 입사 값은 참고로만, 판정은 `unknown`, 실패 없음 — **(v6) 수정: 0°를 포함하는 목표는 수직 입사 판정을 그대로 받음**(13.4절) | 한계식이 수직 입사·PEC에서 유도됨 |
| N5 기록 스냅숏 | 내용 해시 이름의 전체 사본(`snapshots/<sha>.coat`) | 재구성 로직 없이 GUI로 바로 열림, 같은 내용은 한 번만 저장 |
| N6 단위 표기 | 키 접미사, 필드당 하나로 고정. 변수 범위는 `range` + `unit`(확인용) | 숫자를 문자열 파싱 없이 다룸, 스키마가 하나 |

검증하지 못한 주장: Argon은 "agy도 작업공간의 `SKILL.md`를 읽는다"고 했지만 확인하지 못했습니다. 그래서 agy 쪽은 `AGENTS.md` 단락에만 의존합니다.

### 12.5 실험 루프 모의 실행 (v4 → v5)
CLI 구현 전에, 계획 문서만 아는 에이전트라고 가정하고 실험 루프를 끝까지 따라갔습니다. 각 명령이 부를 엔진 함수를 직접 실행해 숫자를 얻었습니다(데모 재료 기준).
시나리오: "에폭시 + 카본블랙 20 vol%, 3 mm, 금속판 위. 8–12 GHz, 0–30°, TE/TM, RL ≤ −15 dB, 총 두께 ≤ 4 mm."

| 단계 | 결과 |
|---|---|
| `bound` | 필요 μs·d ≥ 1.09 mm → 4 mm 안에서는 한계에 걸리지 않음 |
| 기준선 | 최악 −2.1 dB (margin +12.9) |
| 1층 최적화(두께·분율) | 1.95 mm·28 vol%, 최악 −6.4 dB (margin +8.6), 0.8초 |
| 2층 경사형 | 최악 −13.9 dB (margin +1.0~1.06) — 단, 아래층 분율 0.35 |
| 시트 + 스페이서 + 흡수층 | margin +5.3 |
| 3층 | margin +6.9 (2층보다 나쁨, 두께 예산 2.6/4 mm만 사용 — 국소 최적) |
| 분율 상한 0.30으로 2층 | 최선 margin +5.7 (시드에 따라 +5.7 / +6.9) |
| 공차(2층 최선, −15 dB 기준) | 0° 평균 17%, 30° TE **1%**, 30° TM 28% |

발견과 반영:
1. 내장 재료 이름을 파일 없이 볼 방법이 없음 → `materials` 명령(13.7절).
2. 재료 dict 형식(혼합 `model` 값, 분산 항 필드)이 문서에 없음 → 부록 A.
3. **공차 분석이 단일 각도·편광이라 수율을 크게 과대평가**(17% vs 1%) → `tolerance --corners`와 결합 수율, 단일 계산에는 범위 경고(7절, 13.7절).
4. **최적화기가 혼합 모델의 신뢰 범위 밖을 파고듦**: 최선 결과가 Bruggeman 퍼콜레이션 임계(1/3) 바로 위 분율에 의존. ε은 분율 0.30에서 17.5 − j9.9,
   0.35에서 19.0 − j22.8, 0.40에서 16.3 − j41.2로 손실이 급증 → 사용자 합의 범위 규칙(플레이북), `mixture_fraction_range` 경고(13.7절).
5. 국소 최적·시드 의존 → `optimize --restarts`, 플레이북의 "개선 없음" 판정은 다중 시작 기준.
6. Rozanov `ok`인데 목표 미달 — 설계대로("필요조건일 뿐")지만, 목표 미달 시 절충안 보고가 플레이북에 없었음 → 13.5절 7단계.
7. 실행 시간은 한 번에 1~10초(변수 2~6개). v4의 "탐색은 `--maxiter 40 --timeout 60`" 권고는 이 규모에서 불필요 → `estimated_max_evals` 기준으로 바꿈.
한계: 시뮬레이션한 사람이 코드를 알고 있어 문서의 빈틈을 과소평가했을 수 있음 → v5에 대해 블라인드 테스트(문서만 주고 시나리오 수행)를 진행.

### 12.6 블라인드 테스트 (v5 → v6)
v5 문서 한 파일만 주고, 코드를 모르는 두 테스터(Claude 서브에이전트, agy/Gemini Argon — 문서 폴더만 읽기 권한)에게 같은 과제를 동시에 줬습니다.
과제: 두 시나리오에서 사용자 질문, 명세 JSON, 명령 순서와 분기, 짐작·모호·막힘 지점 표, 판정을 쓰기.
- S1: 12.5절과 같은 카본블랙/에폭시 시나리오(v5 수정이 통하는지).
- S2: 처음 보는 시나리오 — 측정 CSV(카보닐철/실리콘, 1–8 GHz), 2–6 GHz 수직 입사 −10 dB, 두께 ≤ 2 mm, "철 함량 50~70 wt%에서 변경 가능".

| | Claude 테스터 | agy 테스터 |
|---|---|---|
| S1 | 조건부 가능(출력 필드 추측) | 대체로 가능(출력 키 추측) |
| S2 | **불가**(blocker 2) | **불가**(blocker 2) |
| 1순위 수정 요청 | 명령별 출력 JSON 예시 + `margin_db` 정의 | 명령별 출력 JSON 예시 + 플레이북 명령 정정 |

공통 발견과 반영:
1. 측정 CSV 재료의 함량을 바꿀 수단이 없음(blocker) → 13.5절 1a, 13.8절(`choices`, `fraction_wt`, `fit`), N9.
2. 기본 sweep(2–18 GHz)이 측정 범위(1–8 GHz)를 벗어나 `material_out_of_range`로 실패(blocker) → 13.2절 측정 범위 검사·`sweep_clamped`.
3. 명령별 출력 JSON 구조가 없음 → 부록 B.
4. 0°를 포함한 목표에서 Rozanov 판정이 항상 `unknown`이라 플레이북의 멈춤 규칙이 발동하지 않음(모순) → **판정 규칙 자체가 틀렸음**: 0°를 포함하는 목표는 수직 입사 판정을 그대로 받음(13.4절).
5. 혼합 분율 경고 구간의 경계 → 닫힌 구간 명시, 이슈 `args`에 구간 포함(13.7절).
한쪽만 발견: 플레이북에 `solve --targets`·`optimize -o` 누락(agy), `param` 자료형 규칙(agy), 수직 입사 목표 표기(agy),
`margin_db` 정의(Claude), 공차 값의 의미(Claude), 수율 기준값(Claude), `spec` 출력 위치(Claude) → 13.2·13.5절, 부록 B.

**행동에서 드러난 위험**: agy 테스터는 "빈틈을 메우지 말고 기록하라"는 지시에도 S2에서 문서에 없는 카보닐철 분산 모델(Δμ = 18, f₀ = 3.5 GHz, "CSV에 맞춘 값")을
지어내 함량 최적화를 진행했습니다. Claude 테스터는 같은 지점을 "수행 불가"로 보고했습니다. 실제 에이전트도 막히면 그럴듯한 가정으로 진행해 근거 없는 결과를 낼 수 있으므로,
플레이북에 "재료 파라미터를 지어내지 말 것, `fit`과 사용자 확인을 거칠 것, 문서에 없는 방법이 필요하면 멈출 것"을 넣었습니다(13.5절 1단계).

### 12.7 열린 질문 결정 (N1, N2, N7~N10)

| 질문 | 결정 | 근거 |
|---|---|---|
| N1 GUI 진단에도 혼합 성분 검사 | **CLI `check`만 넓힘.** GUI는 후속 작업(구현 후 DEVELOPMENT_HISTORY 6장 "미뤄 둔 작업"에 기록) | GUI를 바꾸면 영문·한글 화면 캡처 검증까지 범위가 늘어남 |
| N2 `no_valid_design`의 종료 코드 | **4 유지** + `error.details.first_failure`(7절 `optimize`) | 설정은 유효하나 모든 평가가 계산 실패 → 원인은 모델. 첫 실패 원인을 주면 에이전트가 고칠 곳을 앎 |
| N7 혼합 모델 경고 구간 | **v1은 0.25~0.40(Bruggeman 전도성)·> 0.30(MG) 유지** | 경고일 뿐 계산을 막지 않음. 구간은 이슈 `args`에 들어 있어 근거가 생기면 바꾸기 쉬움 |
| N8 `--corners` 비용 | **기본 표본 수를 줄이지 않음** | 모의 실행에서 공차 분석은 몇 초. 수율 추정 정확도가 더 중요. `--n-samples`로 조절 가능 |
| N9 측정 복합재에서 충전재 물성 역산 | **v1 범위 밖 → (v7) `invert-filler`로 구현**(13.9절) | 처음에는 함량별 CSV를 재료 후보로 두기 / 추가 측정 요청 경로로 처리(13.8절). 13.9절의 MG·Bruggeman 해석적 역변환으로 처리 |
| N10 피팅 모델의 정적 μ로 Rozanov 판정 | **외삽 μs에서는 판정을 `violated`보다 올리지 않음**(13.4·13.8절) | 측정 범위 밖 외삽값은 "불가능하니 멈춤"의 근거로 약함. 경고로만 알리고 `note`에 외삽임을 적음 |

## 13. (v3) 에이전트 실험 루프

### 13.1 목표 워크플로우와 역할 분담
사용자가 **현재 조성**(층 순서, 재료, 혼합 재료의 배합비, 두께)과 **목표**(대역·각도·편광별 RL, 두께·면밀도 제한)를 알려 주면,
에이전트가 이 툴로 시험 계산과 최적화를 반복해 목표에 도달하거나, 도달할 수 없음을 근거와 함께 보고합니다.

```
사용자 설명 ─▶ 명세(spec.json) ─build─▶ design.coat ─check(+limits)─▶ solve(기준선)
                   ▲                                                    │
                   │ 구조 변경(층 추가·재료 교체·변수/범위 조정)         ▼
                   └──────────── 에이전트 판단 ◀── optimize ◀── 변수·범위 설정
                                                     │
                                       목표 충족 ─▶ tolerance ─▶ 보고(+journal)
```

- **안쪽 루프 = 내장 최적화기**: 정해진 구조 안에서 연속 값(두께, 혼합 분율 `fraction`, 시트 R/L/C, 분산 계수)과 재료 후보를 찾습니다.
  수천 번의 평가를 몇 초~몇 분에 끝내므로, 에이전트가 `solve`를 반복 호출해 값을 손으로 찾는 방식보다 훨씬 빠르고 토큰도 적게 듭니다.
  혼합 재료의 부피 분율은 이미 최적화 변수입니다(`MixtureMaterial.params()`, `models.py` 335행 부근, 단위 `frac`).
- **바깥 루프 = 에이전트**: 최적화기가 못 하는 판단을 맡습니다.
  - 무엇을 변수로 풀고 범위를 얼마로 둘지 정합니다(제조 가능한 분율 상한, 두께 단위).
  - 목표 미달이면 원인을 해석합니다. 어느 목표의 `margin_db`가 양수인지, 두께 상한에 걸렸는지 봅니다.
  - **구조를 바꿉니다**: 층 추가, 재료 교체, 저항 시트 삽입. 이것은 `spec` → 명세 수정 → `build`로 합니다.
  - 목표를 충족하면 공차 분석으로 수율을 확인합니다.
  - Rozanov 한계로 불가능한 목표면 멈추고 보고합니다.
- 루프의 멈춤 규칙(시도 횟수·시간 예산, 개선 없음 N회 연속, 한계 위반)은 플레이북(13.5절)에 둡니다. 툴은 판단 근거만 제공합니다.

### 13.2 설계 명세 (`build`, `spec`) — (v4) 전면 개정
`.coat`는 uid, 내부 재료 dict, 경로 튜플 때문에 에이전트가 직접 쓰기 까다롭습니다. 그래서 **사람이 읽는 명세**를 따로 둡니다.
명세는 `Project`가 담는 **모든 정보**를 표현해야 합니다(그래야 `spec` → 수정 → `build` 왕복이 편집 수단이 됩니다).

```json
{
  "spec_version": 1,
  "name": "CB absorber v1",
  "notes": "",
  "incident": "Air",
  "backing": "pec",
  "materials": [
    {"name": "CB mix A", "kind": "mixture", "matrix": "Epoxy", "inclusion": "Carbon black",
     "fraction": 0.20, "model": "bruggeman"},
    {"name": "Measured CI", "csv": "data/ci_measured.csv"}
  ],
  "layers": [
    {"name": "R-card", "sheet": {"model": "constant", "R_ohm": 377, "X_ohm": 0}},
    {"name": "Absorber", "material": "CB mix A", "thickness_mm": 1.5}
  ],
  "sweep": {"f_ghz": [2, 18], "n_f": 401, "log_f": false, "angle_deg": 0, "f_at_ghz": 10,
            "angle_range_deg": [0, 80], "n_angle": 81, "map_n_f": 161, "map_n_angle": 61},
  // 선택 키(개발 이력 3.21–3.23): "uniform_wavelength": true(점을 진공 파장 등간격으로 — 결과가 달라짐, log_f가 켜져 있으면 로그),
  //   "spectral_unit"·"length_unit"(GUI 표시 단위 — 결과·숫자 단위 그대로). `info`의 `sweep`에는 "uniform_wavelength"가 늘 들어갑니다.
  "targets": [
    {"name": "X", "f_ghz": [8, 12], "n_f": 41, "angle_deg": [0, 30], "n_angle": 4,
     "pols": ["TE", "TM"], "goal_db": -20, "enabled": true}
  ],
  "variables": [
    {"layer": "Absorber", "param": "thickness", "range": [0.5, 3.0], "unit": "mm"},
    {"material": "CB mix A", "param": ["fraction"], "range": [0.10, 0.40], "unit": "frac"},
    {"layer": "R-card", "param": "R", "range": [100, 1000], "unit": "ohm"}
  ],
  "choices": [{"layer": "Absorber", "candidates": ["CB mix A", "Measured CI"]}],
  "optimization": {"w_worst": 1, "w_mean": 0, "w_thickness": 0, "w_mass": 0, "rl_ref_db": -20,
                   "thickness_ref_mm": 5, "mass_ref_kg_m2": 5, "thickness_max_mm": 3.0,
                   "maxiter": 150, "popsize": 15, "seed": null, "polish": true},
  "tolerance": {"n_samples": 200, "distribution": "normal", "thickness": 0.05, "eps": 0.05, "mu": 0.05,
                "sheet": 0.05, "eps_loss": 0.10, "mu_loss": 0.10, "target_db": -20,
                "band_ghz": null, "angle_deg": 0, "pol": "avg", "lower_pct": 5, "upper_pct": 95, "seed": 1,
                "per_layer": {"Absorber": {"thickness": 0.02}}}
}
```

규칙:
- **층 순서는 입사파 쪽부터**(GUI 층 목록의 맨 위 = 입사면, AGENTS.md 규약과 같음).
- **층 참조**: 변수·재료 선택·층별 공차에서 층은 이름이나 1부터 세는 번호(정수)로 참조합니다. uid는 `build`가 만들고 명세에는 나오지 않습니다.
  층 이름은 비어 있거나 겹쳐도 됩니다(`.coat`의 기본 층 이름은 빈 문자열). **이름으로 참조할 때만** 그 이름이 유일해야 합니다.
  재료 이름은 항상 유일해야 합니다.
- **단위는 필드마다 하나로 고정**하고 키 접미사로 표시합니다(N6). 같은 양에 다른 접미사를 허용하지 않습니다.
  고정 단위는 GUI 표시 단위와 같습니다: 두께 `_mm`, 주파수 `_ghz`, 각도 `_deg`, 시트 `R_ohm`·`X_ohm`·`L_nh`·`C_pf`(`null` = 커패시터 없음), 질량 `_kg_m2`.
- (v6) **변수의 `param`**: 층 변수는 층 속성 이름 문자열(`"thickness"`, `"R"`, `"X"`, `"L"`, `"C"`). 재료 변수는 **경로 리스트**입니다 —
  재료 파라미터는 중첩될 수 있기 때문입니다(예: `["fraction"]`, `["mu_terms", 0, "delta"]`). 한 단계짜리는 문자열도 받습니다(`"fraction"` = `["fraction"]`).
  쓸 수 있는 경로와 단위는 `materials`·`info`의 `params[]`에 그대로 나옵니다.
- **변수 범위**는 `{"range": [lo, hi], "unit": "<표시 단위>"}`입니다. `unit`은 그 파라미터의 `param_unit()`(`mm`, `ohm`, `nH`, `pF`, `GHz`, `S/m`, `frac`, `""`)과
  **같아야 하며**, 다르면 `invalid_spec`입니다(에이전트가 단위를 잘못 짐작하는 것을 잡기 위한 확인용 필드).
- **시트 층**: `{"model": "constant", "R_ohm", "X_ohm"}`, `{"model": "rlc", "R_ohm", "L_nh", "C_pf"}`(직렬) 또는 `{"model": "parallel_rlc", "R_ohm", "L_nh", "C_pf"}`(병렬). `model`은 필수(`constant`와 `L=0, C=None`인 `rlc`를 구분하기 위해).
  - (병렬 RLC) 1/Zs = 1/R + jωC + 1/(jωL). `L_nh`가 0이면 인덕터가 없고 `C_pf`가 null이면 커패시터가 없습니다. 인덕터가 없는 시트에는 `L` 변수를 둘 수 없고, `L` 변수의 하한은 0보다 커야 합니다(L→0⁺은 단락, L=0은 개방이라 불연속입니다). `info`의 `L_h`는 인덕터가 없으면 null입니다.
  - (각도 의존) RLC 시트는 선택 키 `"angle": {"L_TE", "L_TM", "C_TE", "C_TM"}`를 받습니다. L_pol(θ) = L(1 + a·s²), C_pol(θ) = C(1 + a·s²), s² = (k_x/k₀)² = n_inc² sin²θ이고, 키 없음 = 0입니다. 금속 메시는 `L_TM`, 패치 배열은 `C_TE`가 −1/(2ε_eff)입니다(Luukkonen 2008, 식 5·9). 조밀 배열 전용이며 회절 로브가 생기면 유효하지 않습니다. 모르는 키, 유한하지 않은 값, 상수 시트의 `angle`은 `invalid_spec`입니다. 결과의 L·C가 각도 범위에서 양수가 아니면 `solver_error`이고, `check`는 스윕의 각도 격자도 시험합니다. `info`의 `angle`은 계수가 없거나 상수 시트면 null입니다. 계수는 최적화 변수가 아닙니다.
- **뒷판**: `"pec"` 또는 `{"kind": "halfspace", "material": "<이름>"}`.
- (v6) **수직 입사 목표**는 `"angle_deg": 0`(스칼라)로 씁니다. `[0, 0]`과 같고 `n_angle`은 필요 없습니다. 사입사 한 각도는 `"angle_deg": 45`.
- (v6) **공차 값**(`tolerance`의 `thickness`, `eps`, `mu`, `sheet`, `eps_loss`, `mu_loss`, `per_layer` 값)은 **공칭값에 대한 상대값**입니다(0.05 = 5%).
  `distribution: "normal"`이면 1σ, `"uniform"`이면 ± 반폭입니다(`ToleranceSettings`). 무차원이라 접미사가 없습니다.
  `loss_correlation`(−1…1, 기본 0)은 같은 층의 실수부 오차와 손실 오차(ε′–ε″, μ′–μ″)의 상관계수 ρ입니다. 손실 공차가 있는 곳에만 쓰입니다(스키마 5).
  `per_layer[]` 항목의 `loss_correlation`은 그 층의 ρ로 기본값 대신 쓰입니다(−1…1, 상대값이 아닌 계수, 스키마 6).
  `material_params[]`(스키마 10, 선택)는 재료 파라미터를 표본마다 흔듭니다: `{"material": "<이름>", "param": ["mu_terms", 0, "f0"] 또는 "fraction", "tol": 0.05}`.
  `param`은 `variables[]`의 재료 항목과 같은 키이고 `tol`은 상대값입니다(분포는 위와 같음). 재료 단위 오차라 그 재료를 쓰는 모든 층·혼합 재료가 같은 값을 봅니다.
  값은 파라미터의 물리 범위로 잘립니다. 모르는 재료·파라미터, 음수·비숫자 `tol`, 같은 파라미터의 중복은 `invalid_spec`입니다. 항목이 없으면 `spec` 출력에 키가 없습니다.
  (3.52, 스키마 15) 항목에 `"mode": "absolute"`와 `"unit"`(파라미터의 표시 단위, `variables[]`와 같은 규칙: 분율 `frac`, f₀·γ `GHz`, σ `S/m`, 무차원 `""`)을 주면
  `tol`은 절대 편차입니다(값 = 명목 + Δ, Δ는 정규 1σ 또는 균일 ± 반폭). 상대 모드에 `unit`을 주거나, 절대에 `wt`·다른 단위를 주거나, `mode`가 다르면 `invalid_spec`.
  무게 분율 절대 공차는 받지 않습니다(체적 분율 환산이 명목 함량에 따라 달라짐). 상대 항목의 `spec` 출력은 전과 같습니다.
  (3.49) `tolerance` 결과의 `material_params_clipped`(`[{"path", "n"}]`)가 범위에 걸려 잘린 표본 수이고, 하나라도 있으면 경고 `tolerance_clipped`를 냅니다.
- **목표**: `angle_deg`의 상한이 하한보다 크면 `n_angle`이 필수이고 2 이상이어야 합니다. 빠지면 `invalid_spec` —
  `BandTarget.n_angle` 기본값이 1이라 그대로 두면 `grid()`가 하한 각도만 평가합니다(`project.py:102-110`).
- **재료 dict는 `.coat`와 같은 형식(SI, 접미사 없음)**이라는 예외를 명시합니다. `Material.to_dict()` 그대로이며(`density` kg/m³, `sigma` S/m, 분산 항의 `f0`·`gamma` Hz),
  단위 접미사 규칙은 재료 dict 바깥에만 적용합니다. 측정 CSV는 `{"name", "csv", "density"?, "note"?}`(명세 파일 기준 상대 경로, `materials/csvio.load_csv`).
- **내장 재료**: `build`는 `Project()`의 내장 재료에서 시작합니다. 명세에 같은 이름이 있으면 덮어쓰고, `"remove_builtin": ["PTFE", …]`로 지울 수 있습니다.
  `spec`은 `m.to_dict() == builtin.to_dict()`(note 포함, `Air` 포함)인 재료만 생략하고, 지워진 내장 재료는 `remove_builtin`에 적습니다.
  (`is_builtin_demo()`는 `Air`를 데모로 보지 않고 note를 무시하므로 이 판정에 쓰지 않습니다 — `checks.py:31-42`.)
- (v5) 재료 dict의 종류별 필드는 **부록 A**에 있습니다. `materials` 명령은 내장 재료를 이 형식 그대로 보여 줍니다.
- (v5) **재료 이름에 배합비를 넣지 않습니다**(예: "CB 20%" 대신 "CB mix A"). 분율을 최적화하면 이름이 거짓이 되기 때문입니다.
- **혼합 재료는 2성분**(매트릭스 + 충전재 하나)입니다. 3성분 이상은 혼합 재료를 중첩해 표현하며, 플레이북에 분율의 의미(바깥 혼합 기준)를 적습니다.
  내장 `"Carbonyl iron / epoxy"`는 이미 복합재이므로 다시 에폭시에 섞으면 "희석"이라는 점도 플레이북에 적습니다.
- (v6) **측정 재료와 주파수 범위**: Tabulated 재료(측정 CSV)는 측정 범위 밖을 계산하지 않습니다. `build`는 다음을 검사합니다.
  - 활성 목표·`tolerance.band_ghz`가 사용 중인 측정 재료의 범위(끝점 포함)를 벗어나면 `invalid_spec`(`details`: 재료, 측정 범위, 요청 범위).
  - `sweep`을 **생략했으면** 기본값(2–18 GHz) 대신 사용 중인 측정 재료 범위의 교집합으로 정하고, 결과 `warnings`에 `sweep_clamped`로 알립니다.
  - `sweep`을 **명시했는데** 범위를 벗어나면 `invalid_spec`. (`check`도 같은 검사를 `sweep_outside_data` 이슈로 냅니다.)
- (v6) **무게 분율**: 혼합 재료는 `fraction`(부피) 대신 `fraction_wt`(무게, 0~1)를 받을 수 있습니다. `build`는 성분 밀도로 부피 분율로 바꿉니다:
  `φ = (w/ρ_inc) / (w/ρ_inc + (1−w)/ρ_mat)`. 두 성분 모두 `density`가 있어야 하고(내장 재료의 밀도는 데모 값), 결과 `warnings`에 환산값을 적습니다.
  변수도 `{"material", "param": ["fraction"], "range": [0.5, 0.7], "unit": "wt"}`로 쓸 수 있고, `build`가 범위를 부피 분율로 바꿉니다(단조 변환).
  `info`·`optimize`는 해당 변수에 `value_wt`를 함께 냅니다. **측정 CSV 재료의 함량은 바꿀 수 없습니다**(13.8절).
- 생략한 섹션은 `Project` 기본값을 씁니다. 단 **`targets`를 생략하면 목표 없음**으로 둡니다(기본 8–12 GHz 목표를 쓰지 않음) —
  의도하지 않은 목표로 최적화하는 일을 막기 위해서입니다(`optimize`는 `invalid_optimization_settings`로 거부).
- `build SPEC -o OUT.coat`: 검증 → `Project` 조립 → 저장. 명세 오류는 `invalid_spec`(종료 3, `details.path`에 JSON 경로, 예: `layers[1].thickness_mm`).
- (v6) `spec FILE.coat [-o OUT.json]`: `-o`가 없으면 명세를 봉투의 `result.spec`에, 있으면 **봉투 없는 순수 명세**를 파일에 쓰고 봉투에는 `result.output_path`만 둡니다
  (`build`에 그대로 넘길 수 있게). 에이전트가 손으로 값을 옮기지 않아도 됩니다.
- `spec FILE.coat`: `Project` → 명세. 층을 이름으로 참조할 수 없으면(빈 이름·중복) 번호로 참조합니다. Tabulated 재료는 측정값 배열을 dict 안에 그대로 넣습니다.
- **왕복 보장**: 내장 예제 7개 모두에서 `build(spec(p))`의 `to_dict()`가 `p`와 같습니다. uid는 제외하고, 실수는 `rtol=1e-12`로 비교합니다
  (표시 단위 ↔ SI 환산에서 생길 수 있는 마지막 자리 오차 때문. `0.08e-12` 같은 값은 실제로는 정확히 돌아오는 것을 확인했지만 일반적으로 보장되지 않음).
  예제가 실제로 쓰는 필드 — sweep 변경(5개), notes(3개), `maxiter=120`(2개), 이름과 `n_angle=4`가 있는 목표(dualband), RLC 시트(cara) — 가 모두 왕복 대상입니다.

### 13.3 실험 기록 (`--journal DIR`, `journal`)
- `solve`·`optimize`·`tolerance`·`check`에 `--journal DIR [--note TEXT]`를 주면 CLI가 기록을 남깁니다. **에이전트가 아니라 툴이 쓰므로** 기록이 빠지거나 꾸며지지 않습니다.
  - `DIR/journal.jsonl`에 한 줄 추가: `{"seq", "ts", "command", "argv", "note", "input": {"path", "sha256"}, "snapshot", "spec_fingerprint", "summary", "seed_used", "exit_code", "stopped", "output_snapshot"}`
  - **스냅숏(N5)**: 입력 `.coat`를 내용 해시로 이름 지은 전체 사본 `DIR/snapshots/<sha256 앞 12자리>.coat`로 남깁니다. 같은 내용은 한 번만 저장하고, GUI에서 바로 열 수 있습니다.
    `optimize -o`의 결과 파일도 같은 방식(`output_snapshot`)입니다.
  - **`spec_fingerprint`**: 활성 목표 목록과 `thickness_max`의 해시입니다. 목표나 제한이 바뀐 시도끼리는 margin을 비교할 수 없기 때문입니다.
  - `summary`: `solve`는 편광별 최선 RL과 총 두께, 그리고 **활성 목표가 있으면 `--targets`가 없어도** 목표별 `worst_rl_db`·`margin_db`
    (기록이 있을 때 시도끼리 비교할 수 있게 하기 위해). `optimize`는 `terms`와 목표별 margin, `tolerance`는 수율과 `target_db`, `check`는 이슈 수와 한계 판정.
- `journal DIR`: 시도 목록과 **같은 `spec_fingerprint` 묶음별 최선 설계**(최대 margin이 가장 작고 `thickness_max`를 지키는 시도), 시도별 note를 요약합니다.
  목표가 중간에 바뀌었으면 그 사실을 경고로 냅니다.
- 동시 실행은 지원하지 않습니다(한 루프 = 한 기록 폴더). 쓰기는 줄 단위 추가라 중간에 끊겨도 앞 기록은 유효합니다.

### 13.4 물리 한계 검사 (Rozanov) — (v4) 개정
금속 뒷판 흡수체에는 두께의 이론적 하한이 있습니다(K. N. Rozanov, IEEE Trans. Antennas Propag. 48(8), 2000).
수직 입사, **PEC 뒷판**에서 `|∫₀^∞ ln|Γ(λ)| dλ| ≤ 2π² Σᵢ μs,i·dᵢ` 이고(μs = 정적 투자율, λ = 입사 매질 안의 파장),
목표 대역 `[λ₁, λ₂]`에서 `|Γ| ≤ Γ₀`를 요구하면 **필요조건 `Σ μs,i·dᵢ ≥ |ln Γ₀|·(λ₂ − λ₁) / (2π²)`**가 나옵니다(Γ₀ = 10^(goal_db/20)).
예: 공기 중, 8–12 GHz, −20 dB → `Σ μs·d ≥ 1.457 mm`(직접 계산으로 확인). 비자성(μs = 1)이면 두께 1.46 mm 미만으로는 불가능합니다.

- **적용 조건**: `backing.kind == "pec"`일 때만 판정합니다. halfspace 뒷판은 투과가 있어 두께 0으로도 Γ = 0이 될 수 있으므로 `status: "unknown"`(note: PEC 뒷판 전제).
  입사 매질이 공기가 아니면 λ를 `λ₀ / √(ε_inc·μ_inc)`로 바꿉니다(입사 매질은 무손실이라는 것이 이미 solver 조건, `solver.py`의 입사 매질 검사).
- `limits.py`(Qt 없음):
  - `rozanov_required_mu_d(f_lo, f_hi, goal_db, n_inc=1.0) -> float` [m]
  - `static_permeability(material, resolver) -> float | None` — **모델식에서 해석적으로** μ(f→0)을 구합니다(1 Hz 평가는 쓰지 않음: 공명 주파수가 매우 낮은 항, 불필요한 ε 계산 문제).
    - `ConstantMaterial`: `mu_loss == 0`이면 `mu_re`. `mu_loss > 0`이면 `None` — 주파수와 무관한 상수 μ″는 인과적이지 않아, 크라머스–크로니히 관계상 실제 μs는 `mu_re`보다 큽니다(과소평가 방지).
    - `DispersiveMaterial`: 상수 `mu_loss == 0`이고 모든 μ 항이 `delta ≥ 0`, `f0 > 0`이면 `mu_inf + Σ delta`(Debye·Lorentz 모두 f→0에서 Δ). 아니면 `None`.
      (참고: 내장 `Carbonyl iron / epoxy`는 4.0. 1 Hz에서 `eps_mu`로 구한 값과 같음을 확인했습니다.)
    - `MixtureMaterial`: 성분의 μs를 재귀로 구해(순환 방지) 같은 혼합 규칙(MG/Bruggeman)을 실수 μs에 적용. 성분 중 하나라도 `None`이면 `None`.
    - `TabulatedMaterial`: `None`(측정 범위 밖을 외삽하지 않는다는 원칙).
  - `design_mu_d(project) -> float | None`: 현재 설계의 슬랩 `Σ μs·d`. 하나라도 `None`이면 `None`. 시트 층은 두께 0이라 기여가 없습니다.
  - `max_achievable_mu_d(project) -> float | None`: 최적화로 도달할 수 있는 최대 `Σ μs·d`.
    층마다 **현재 재료와 `MaterialChoice` 후보 중 최대 μs**, μs를 바꾸는 재료 변수(`fraction`, `mu_re`, `mu_inf`, `mu_terms[i].delta`)는 **범위의 상한**에서 평가하고,
    두께는 변수면 상한, 아니면 현재 값. `thickness_max`가 있으면 μs가 큰 층부터 두께를 채우는 탐욕적 배분으로 상한을 구합니다. 하나라도 `None`이면 `None`.
- `check`의 `result.limits[]`: 활성 목표마다 `{"target", "required_mu_d_m", "design_mu_d_m", "max_achievable_mu_d_m", "status", "note"}`.
  - `status`: `"ok"`(현재 설계가 필요조건을 만족) / `"violated"`(현재 설계는 위반, 최적화 범위 안에서는 만족 가능) /
    `"infeasible"`(최적화 범위를 다 써도 위반) / `"unknown"`(PEC 아님, μs를 알 수 없음, 사입사 전용 목표).
  - `ok`는 "가능하다"가 아니라 "이 필요조건에 걸리지 않는다"는 뜻입니다(문서와 `note`에 명시).
  - (N10) μs가 피팅 모델의 외삽값인 재료가 판정에 들어가면 `infeasible` 대신 `violated`로 냅니다(13.8절).
  - 이슈는 **둘 다 경고 수준**입니다: `rozanov_limit`(violated), `rozanov_infeasible`(infeasible). 오류로 두면 의욕적인 목표만으로 `check`가 실패(종료 4)하는데,
    도달할 수 없는 목표도 "최선의 RL을 찾는" 정상 사용입니다(예: `cara` 예제는 −20 dB 기본 목표에 −14.6 dB까지). 판단은 플레이북의 멈춤 규칙이 합니다.
  - **사입사(N4) — (v6) 수정**: 목표의 각도 범위가 **0°를 포함하면** 그 목표는 0°에서도 만족해야 하므로, 수직 입사 판정(`violated`/`infeasible`)이 **그대로 적용됩니다**
    (한계는 수직 입사에서 엄밀한 필요조건). v4·v5에서 `unknown`으로 낮추던 규칙은 틀렸습니다 — 이 때문에 플레이북의 "`rozanov_infeasible`이면 멈춤"이
    0–30° 같은 흔한 목표에서 절대 발동하지 않는 모순이 있었습니다(12.6절). `note`에는 "수직 입사 조건만 검사, 사입사 조건은 더 엄격할 수 있음"을 적습니다.
    0°를 포함하지 않는 목표(예: 30–60°)만 `unknown`입니다.
  - 중복 제거 키는 `(code, material, target index, message)`입니다 — 목표가 여럿이면 `rozanov_*` 이슈가 하나로 합쳐지지 않게.
- `bound --f-ghz LO HI --goal-db G [--mu-s M]`: 파일 없이 필요한 `μs·d`와 `μs = M`일 때 최소 두께를 냅니다(공기 입사, PEC 전제를 결과에 명시). `"input": null`.
- 테스트: 위 수치(1.457 mm), 재료 종류별 `static_permeability`(상수 손실·Tabulated → `None`, Debye·Lorentz → `mu_inf + Σ delta`, MG/Bruggeman 혼합),
  Salisbury 예제가 `ok`, 한계보다 얇은 단일층이 `violated`, 두께 상한이 낮으면 `infeasible`, 재료 후보에 고투자율 재료를 넣으면 `infeasible`이 풀림, halfspace 뒷판이 `unknown`.
- 새 이슈 코드 `rozanov_limit`·`rozanov_infeasible`은 `_ISSUES_EN`에 넣고 KO 항목도 추가합니다(GUI 진단에는 이번에 연결하지 않음).

### 13.5 에이전트 플레이북
툴 사용법과 별개로 **실험 루프의 절차와 멈춤 규칙**을 문서로 둡니다: `docs/AGENT_PLAYBOOK.md`(영어, 에이전트가 읽는 문서).
1. 입력 확인: 사용자 설명에서 층·재료·배합비·두께·목표를 뽑고, 빠진 값은 **추측하지 말고 묻습니다**.
   재료가 내장 데모 값(`demo_values` 이슈)이면 "실측 데이터가 아니므로 결과는 참고용"이라고 반드시 알립니다.
   (v6) **재료 파라미터를 지어내지 않습니다.** 측정 CSV에 맞춘 분산 모델이 필요하면 `fit`을 쓰고 잔차(`rms_eps`, `rms_mu`)와 함께 사용자 확인을 받습니다.
   문서에 없는 방법으로 진행해야 할 것 같으면 멈추고 사용자에게 알립니다.
   (v6) 수율 기준(결합 수율 몇 % 이상)을 묻습니다. 답이 없으면 기본 80%로 두고 보고에 명시합니다.
1a. (v6) **측정 재료(CSV)가 있으면**: sweep과 목표를 측정 범위 안에 둡니다(`build`가 검사). 사용자가 함량(배합비)을 바꾸고 싶어 하면
    측정 CSV는 그 함량 하나의 데이터라 함량을 바꿀 수 없다고 설명하고, 다음 중에서 고르게 합니다(13.8절):
    (a) 함량별로 측정한 CSV 여러 개 → 재료 후보(`choices`)로 이산 탐색, (b) 성분 재료(매트릭스·충전재)의 데이터가 있으면 혼합 재료 + `fraction_wt`,
    (c) 둘 다 없으면 두께만 최적화하고, 함량 탐색에는 추가 측정이 필요하다고 보고.
2. `bound`로 목표의 현실성 확인 → `build` → `check`. 오류면 고칩니다. `result.limits[].status`가 `infeasible`(`rozanov_infeasible`)이면
   사용자에게 목표·두께 상한 조정이나 고투자율 재료 추가를 제안하고 멈춥니다. (v6) 0°를 포함하는 목표에도 이 판정이 그대로 적용됩니다(13.4절).
3. (v6) `solve --targets --summary-only --journal DIR`로 기준선을 기록합니다. `--targets`가 있어야 stdout에 목표별 margin이 나옵니다(부록 B).
4. 변수·범위 설정 → (v6) `optimize -o <다음 파일>.coat --restarts 3 --journal DIR`. `-o` 없이는 결과가 저장되지 않습니다.
   `result.targets[].margin_db`(부록 B)를 보고 다음 수를 정합니다. **`margin_db = worst_rl_db − goal_db`, 0 이하면 충족, 양수면 그만큼 미달**입니다.
   - (v5) **변수 범위는 사용자와 합의한 제조 가능 범위**로 정합니다. 사용자가 범위를 말하지 않았으면 묻습니다(예: "배합비는 몇 vol%까지 가능합니까?").
     특히 혼합 분율은 `check`의 `mixture_fraction_range` 경고 구간을 넘지 않게 둡니다. 최적화기는 모델이 믿기 어려운 영역(퍼콜레이션 근처)을 파고듭니다.
   - (v5) 실행 시간은 `info`·`check`의 `estimated_max_evals`로 가늠합니다(모의 실행: 변수 2~6개에서 수천~2만 번 평가, 1~10초).
     재료 후보(choices)는 조합 수만큼 곱해지므로, 예상 평가가 수십만을 넘으면 `--maxiter`를 줄이거나 `--timeout`을 에이전트의 도구 호출 시간 제한보다 짧게 둡니다.
   - **두께 상한으로 목표를 맞출 때는 `w_thickness = 0`**: 두께 항이 RL과 맞바꿔져 목표 전에 멈추는 것을 막습니다.
   - 모든 margin ≤ 0: 5단계로.
   - 두께 변수가 상한에 붙음: 상한 완화를 사용자에게 제안하거나 고투자율 재료·층 추가를 검토합니다.
   - 특정 대역·각도만 미달: 층 추가(경사형·Jaumann형), 저항 시트 삽입, 재료 후보 추가를 검토합니다(`spec` → 명세 수정 → `build`).
   - (v5) 층을 늘렸는데 결과가 나빠지면 국소 최적을 의심합니다(모의 실행에서 3층이 2층보다 나빴음). 이전 최선 설계를 출발점으로 두고 다시 돌립니다.
5. (v5) `tolerance --corners --target-db <목표 goal_db> --journal DIR`로 **목표의 각도 끝 × 편광마다** 수율을 확인하고, 결합 수율을 보고합니다.
   (3.19) 각도 범위가 있는 목표는 `--angle-grid`(필요하면 `--n-angle`로 더 촘촘히)로 범위 안쪽 각도까지 확인합니다.
   단일 각도 수율만 보고하면 안 됩니다(모의 실행: 0° 평균 17%, 30° TE 1%). 낮으면 결과에 위험을 명시합니다.
6. 멈춤 규칙: 목표 충족 + 수율 기준(1단계에서 정한 값, 기본 결합 수율 80%) 충족 / 시도 예산(기본 20회 또는 사용자가 정한 값) 소진 /
   같은 목표에서 **다중 시작(`--restarts 3`) 기준으로** 연속 3회 개선 없음 / `rozanov_infeasible`.
7. 보고: `journal DIR` 요약 + 최종 설계의 명세(`spec`) + `seed_used`(재현용) + 남은 위험(데모 재료, 수율, 사입사 근사, 혼합 모델 범위).
   (v5) **목표에 못 미쳤으면** 최선 margin과 함께 절충안을 계산해 제시합니다: 목표를 최선값 근처로 완화했을 때, 두께 상한을 늘렸을 때,
   각도 범위를 줄였을 때 각각 다시 최적화한 결과. 사용자가 다음 결정을 할 수 있게 하기 위해서입니다.

### 13.6 에이전트 연결 방식 (N3) — (v4) 결정: CLI + Skill/플레이북
쓰는 에이전트는 Claude Code와 agy(Antigravity CLI, Gemini)입니다. 한 번의 루프는 수~수십 회 시도이고, `optimize` 한 번은 수 초~수 분입니다.

| 방식 | 장점 | 단점 |
|---|---|---|
| A. CLI만 | 어떤 에이전트·스크립트·CI에서도 씀. 의존성 없음 | 루프 절차 지식이 없음. 사용법을 매번 `--help`로 읽음 |
| **B. CLI + Skill/플레이북 (채택)** | A의 장점 + 절차·멈춤 규칙을 실험할 때만 읽음(컨텍스트 비용 작음) | 에이전트마다 등록 방식이 다름. 인자 검증은 실행 시점에야 됨 |
| C. MCP 서버 | 도구별 입력 스키마, 상태 유지, 프로토콜 수준 진행·취소 | 새 의존성, 서버 관리, stdio 오염에 민감, 긴 호출은 시작/조회/결과로 나눠야 함, 스키마가 무관한 세션 컨텍스트도 차지 |
| D. Python API 직접 | 가장 유연 | 출력·오류 규약 없음, 매번 스크립트 작성, GUI와 같은 숫자 보장 경로를 에이전트가 알아야 함 |

**결정: B.** 근거(Argon 2차 리뷰와 일치):
- 무거운 반복은 `optimize` 안에서 돕니다. 바깥 루프는 5~50회라 프로세스 시작 비용(엔진 import 포함 호출당 약 0.3초, 첫 실행 0.8초 — 이 맥북에서 측정)은 무시할 만하고,
  MCP의 메모리 상태는 이득보다 "디스크 파일과 메모리 상태가 어긋나는" 버그 위험이 큽니다.
- 긴 `optimize`는 두 에이전트가 이미 가진 셸의 백그라운드 실행·시간 제한·Ctrl-C와 CLI의 `--timeout`·종료 코드 5로 충분합니다.
  MCP로 하면 시작/조회/취소 도구가 필요하고 에이전트가 상태 조회로 토큰을 씁니다.
- 실험 기록이 파일 기반이라, 모든 시도를 `journal.jsonl`의 `argv`로 다시 실행할 수 있습니다.
- 새 의존성이 없어 CI(3 OS × Python 3.10/3.13) 테스트가 단순합니다.

**만들 것**: `docs/AGENT_PLAYBOOK.md`, Claude Code 스킬 `.claude/skills/coating-experiment/SKILL.md`(설명 + 플레이북 링크),
`AGENTS.md`에 짧은 단락(agy는 `AGENTS.md`를 항상 읽음. agy가 작업공간 `SKILL.md`도 읽는다는 주장은 확인하지 못해 의존하지 않음).

**만들지 않을 것**: MCP 서버 코드와 `[mcp]` extra. `commands.py`를 순수 함수로 두는 것(8절)만으로 나중에 얇은 래퍼를 붙일 수 있습니다.

**MCP로 넘어갈 조건**: (a) 셸 도구가 없는 MCP 클라이언트(예: 코드 실행 없는 데스크톱 앱)에 연결해야 할 때,
(b) 에이전트가 `optimize` 밖에서 한 세션에 단일 `solve`를 수백 번 부르는 사용 패턴이 실제로 관찰되어 프로세스 시작 비용이 병목이 될 때.

### 13.7 (v5) 모의 실행으로 추가한 명령·옵션
- **`coating-cli materials [--name N]`**: 내장 재료(`builtin_materials()`) 목록. 항목마다 `name`, `kind`, `note`, `is_demo`(`is_builtin_demo`, `Air`는 false),
  `dict`(부록 A 형식 그대로 — 명세 `materials[]`에 복사해 쓸 수 있음), `params[]`(`path`, `label`, `unit`), `static_mu`(13.4절, 알 수 없으면 `null`).
  `"input": null`. 사용자 라이브러리 파일은 `--library PATH`로 함께 보여 줍니다(`materials/library.load_library`).
- **`tolerance --corners`**: 활성 목표마다 꼭짓점 집합 `{angle_min, angle_max} × pols`(중복 제거)를 평가합니다. (3.19) 구현은 `tolerance.run_tolerance_targets`로,
  표본을 한 번 뽑고 표본마다 서로 다른 각도마다 한 번 풀며, 각 행은 그 점의 `run_tolerance`와 비트 단위로 같습니다. 아래 설명은 그 성질을 그대로 따릅니다.
  수율 기준 대역은 그 목표의 주파수 대역, `target_db`는 `--target-db`(없으면 그 목표의 `goal_db`).
  - `run_tolerance`의 섭동 표본은 시드와 층 구성만으로 정해지고 각도·편광과 무관하므로(`tolerance.py`의 `factors`는 계산 루프 전에 뽑힘),
    **같은 시드면 꼭짓점마다 같은 표본**입니다. 그래서 표본별 `worst_db`를 꼭짓점에 걸쳐 모아 **결합 수율**(모든 꼭짓점을 동시에 만족하는 표본 비율)을 정확히 계산합니다.
  - 결과: `corners[]`(`target`, `angle_deg`, `pol`, `yield_fraction`, `worst_db` 통계), `joint_yield_fraction`, `min_corner`.
  - 꼭짓점만 보므로 각도 범위 안쪽의 더 나쁜 각도를 놓칠 수 있습니다(문서와 결과 `note`에 명시). (3.19) 안쪽 각도는 `--angle-grid`로 확인합니다(DEVELOPMENT_HISTORY 3.19).
- **`mixture_fraction_range` 이슈**(경고, `check`와 `optimize` 사전 점검): 혼합 모델이 신뢰하기 어려운 분율.
  - Bruggeman이고 충전재가 전도성(분산 재료의 `sigma > 0` 또는 대상 대역에서 ε″/ε′ > 1)이면 분율 0.25~0.40(퍼콜레이션 임계 1/3 주변, N7).
  - Maxwell–Garnett이면 분율 > 0.30(희박 구형 입자 가정).
  - 현재 분율뿐 아니라 **`fraction` 변수의 범위가 이 구간과 겹쳐도** 냅니다. `_ISSUES_EN` 문구 + KO 항목 추가.
  - (v6) **경계는 닫힌 구간**입니다: Bruggeman 전도성은 `0.25 ≤ φ ≤ 0.40`, MG는 `φ > 0.30`. 범위 상한이 0.25면 경고가 납니다.
    경고 없이 탐색하려면 상한을 0.25 미만(예: 0.24)으로 둡니다. 사용자가 그 이상을 허용하면 경고는 정상이며, 보고에 "모델 신뢰 범위 밖 포함"을 적습니다.
    (12.5절 모의 실행의 상한 0.30은 경고 구간 안을 일부러 탐색한 것입니다.)
  - 이슈 `args`에 경고 구간(`lo`, `hi`)과 모델을 넣어, 에이전트가 경계를 문서에서 찾지 않아도 되게 합니다.
- **`optimize --restarts N`**: 7절 참고.

### 13.8 (v6) 측정 재료로 실험하기: `fit`, 함량 변경
- **측정 CSV(Tabulated)는 그 시편 하나의 데이터**입니다. 두께는 바꿀 수 있지만 함량(배합비)은 바꿀 수 없습니다. 함량을 탐색하려면:
  1. **함량별 측정 CSV가 여러 개** → 각각 재료로 등록하고 층의 재료 후보(`choices`)로 둡니다. 이 경우 재료 이름에 함량을 넣어도 됩니다(값이 고정이므로, 13.2절 이름 규칙의 예외).
  2. **성분 재료 데이터가 있음**(매트릭스, 충전재 각각의 ε·μ) → 혼합 재료 + `fraction_wt`/`fraction` 변수. 혼합 모델 오차가 있으므로 결과는 실제 시편을 만들어 다시 측정해 확인해야 한다고 보고합니다.
  3. **둘 다 없음** → 매트릭스 물성과 실제 함량을 알면 `invert-filler`(13.9절)로 충전재 유효값을 구합니다. 그것도 없으면 두께만 최적화하고, 함량 탐색에는 추가 측정이 필요하다고 보고합니다. **성분 물성을 짐작해 만들지 않습니다.**
- **`coating-cli fit CSV [--name N] [--eps-debye K] [--eps-lorentz K] [--eps-hn K] [--sigma] [--eps-const-loss] [--mu-debye K] [--mu-lorentz K] [--mu-hn K] [--mu-const-loss] [--density RHO]`**
  - `materials/fitting.fit_dispersive`를 부릅니다(Debye·Lorentz·Havriliak-Negami 항은 인과적이라 측정 범위 밖에서도 계산은 됨).
    `--eps-hn`·`--mu-hn`은 Havriliak-Negami 항 수입니다(α, β를 0.05~1에서 맞춤). Debye 항 하나로 맞지 않는 넓은 완화(고분자, 탄소 복합재)에 씁니다.
  - 결과: `material`(부록 A의 `dispersive` dict, 명세에 그대로 사용), `rms_eps`, `rms_mu`(최대 |ε|·|μ| 대비 상대 잔차), `data_range_hz`, `warnings`.
  - 잔차가 크면(예: 0.05 초과) 경고 `fit_poor`를 냅니다. 항 수를 늘려 보라는 안내를 함께 냅니다.
  - 용도: 측정 범위 밖(예: 더 넓은 sweep)을 계산하거나, 정적 투자율을 추정할 때(Rozanov). 이때 `static_mu`는 **외삽 추정**이므로 `limits[].note`에 "fitted model, extrapolated"를 적습니다.
    (N10 결정) 외삽 μs가 들어간 판정은 `infeasible`로 올리지 않고 **`violated`까지만** 냅니다(경고 `rozanov_limit`). 플레이북의 "`infeasible`이면 멈춤"이 외삽값만으로 발동하지 않게 하기 위해서입니다.
    피팅 재료는 `fit`이 붙이는 note 접두사 `"fitted:"`(예: `"fitted: ci_sheet.csv, 1-8 GHz"`)로 알아봅니다.
  - `fit`은 측정 데이터를 대체하지 않습니다. 플레이북은 맞춘 모델을 쓸 때 사용자 확인을 받게 합니다(13.5절 1단계).

### 13.9 (v7) 충전재 유효 파라미터 역산: `invert-filler` (N9)
복합재 한 시편의 측정 CSV, 매트릭스 물성, 함량, 혼합 모델에서 충전재의 **혼합 모델에 묶인 유효 파라미터**를 주파수별 표로 구합니다. 결과는 `MixtureMaterial`의 `inclusion`으로 쓰고, `fraction`을 연속 변수로 최적화합니다. 따로 측정한 충전재 물성이 아닙니다.

**시제품에서 정해진 방향** (합성 데이터, 1 % 복소 잡음):
- 충전재 값 자체는 악조건입니다. 잡음이 2~14 %(ε=30−5j), 2~35 %(100−20j), 전도성 충전재에서는 사실상 100 %로 커집니다.
- 그래도 같은 모델로 다른 함량(φ/2, 1.5φ)을 예측한 복합재 값은 대개 0.2~2 % 오차입니다. 큰 위험은 **모델 불일치**(Bruggeman 데이터를 MG로 처리: 비전도성 1~17 %, 전도성 φ≥0.2에서 12~100 %)입니다. 함량 입력 오차(0.20→0.22)도 예측을 5~7 % 흔듭니다.
- 저장소에 같은 재료계의 함량별 실측 세트가 없어 합성 데이터로만 검증합니다.

**역변환** (단일 비율로 계산해 중간값 넘침을 피함, ε·μ 공용, 0 < φ < 1):
- MG: ei = em·[φ(e+2em)+2(e−em)] / [φ(e+2em)−(e−em)], β = (e−em)/[φ(e+2em)]
- Bruggeman: ei = e·[φ(em+2e)−2(1−φ)(em−e)] / [φ(em+2e)+(1−φ)(em−e)], g = −(1−φ)(em−e)/[φ(em+2e)]

**점별 판정** (`materials/inversion.py`, Qt 없음):
- `outside_model`: Re β 또는 Re g ≥ 1 − 1e-9. 복합재 값이 그 모델이 수동 충전재로 낼 수 있는 차폐 한계를 넘은 것입니다. 왕복 오차와 수동성 검사를 모두 통과하면서도 다른 함량에서 극점(1 − φβ = 0)에 가까워지므로 별도로 잡습니다(Argon 지적, 실험으로 확인).
- `gain`: 손실이 음수(허수부 > 1e-12·max(|값|, 1), `checks.check_material`과 같은 허용치). 허용치 안의 부호 잡음은 0으로 둡니다.
- `branch`: 왕복 오차 > 1e-6. Bruggeman의 근 선택이 다른 가지로 갔다는 뜻입니다.
- 위 셋 중 하나라도 있으면 기본은 오류 `inversion_nonphysical`(종료 4)이고 파일을 쓰지 않습니다. `error.details`에 점 수, 범위, 증폭률을 모두 넣습니다.
- `--clamp-nonpassive`는 **`gain`이면서 Re(ei) > 0이고 `outside_model`이 아닌 점만** 손실을 0으로 자릅니다. Re(ei)의 부호가 뒤집힌 점을 자르면 표의 선형 보간이 Fröhlich 극점을 지나 예측이 격자 사이에서 수십 배 튑니다(실험: 최대 45배). 이런 점은 옵션을 줘도 오류입니다.
- 전도성 충전재처럼 식별이 안 되는 데이터는 대개 이 오류로 끝납니다. 값을 만들어 내지 않고, 함량별 측정이나 성분 데이터가 필요하다고 보고합니다.

**진단 지표**:
- `amplification`: κ = |∂ei/∂e|·|e/ei|(해석식, 측정 오차가 충전재 값에 몇 배로 커지는지). 복합재와 매트릭스가 같은 채널(예: μ=1)은 제외합니다. κ > 20이면 경고 `filler_ill_conditioned`.
- κ는 예측 오차를 말해 주지 않으므로 예측 지표를 함께 냅니다. φ₀/2, min(1.5φ₀, 0.95)에서 (a) `fraction_sensitivity`: φ₀를 ±10 % 바꿔 다시 역산했을 때의 예측 변화, (b) `model_disagreement`: 다른 혼합 모델로 역산·예측했을 때의 차이(다른 모델이 판정에 걸리면 null과 이유). 0.10 초과 시 경고.
- `validation[]`: `--validate CSV FRACTION`으로 다른 함량의 측정과 비교합니다. rms는 `fitting`과 같게 √mean|예측−측정|² / max|측정|. 겹치는 점이 2개 미만이면 오류, 0.10 초과면 `validation_poor`. 검증이 없으면 `no_validation`.
- Re(ei) < 0 점은 금속성 충전재에서 있을 수 있어 오류로 하지 않고 경고 `filler_negative_real`.

**명령**: `coating-cli invert-filler COMPOSITE.csv -o FILLER.csv --model {maxwell_garnett,bruggeman,odelevskiy,gem} [--shape-n N --percolation PC | --percolation PC --exponent T] --density-filler R (--fraction V | --fraction-wt W --density-matrix R) (--matrix-csv F | --matrix-eps RE LOSS [--matrix-mu RE LOSS]) [--name N] [--clamp-nonpassive] [--validate CSV FRACTION]... [--force]`
- 모델·매트릭스·함량·충전재 밀도는 모두 필수이고 기본값이 없습니다. 재료 값을 지어내지 않기 위해서입니다(밀도를 기본값으로 두면 `fraction_wt`와 질량 목적함수가 조용히 틀어집니다). 내장 재료(데모 값)는 매트릭스로 받지 않습니다.
- `--validate`의 FRACTION은 주 함량과 같은 기준(`--fraction-wt`를 쓰면 무게 분율)입니다. 결과의 `fraction`은 어느 쪽으로 넣어도 부피 분율입니다.
- `-o`는 필수이고, 어떤 입력 CSV와도 같은 경로면 `--force`가 있어도 거부합니다. CSV 읽기 오류는 `fit`과 같이 종료 3입니다.
- 결과의 `material.csv`는 절대 경로입니다. 명세는 상대 경로를 명세 폴더 기준으로 풀기 때문에, 그대로 붙여도 깨지지 않게 합니다.

**출처 보존** (`SCHEMA_VERSION` 유지): note `inverted: comp.csv; model=bruggeman; fraction=0.2; matrix=...`를 CSV 머리 주석에도 씁니다. `load_csv`가 이 주석을 `note`로 읽으므로 GUI 가져오기와 `{"name","csv"}` 명세에서도 유지됩니다. `fit`은 이 표식을 지우지 않고(`fitted: …; inverted: …`) 경고 `fit_of_inverted`를 냅니다.

**진단 경고** (`limits.mixture_range_issues` 안, 그래서 `check`, CLI `optimize` 사전 점검, GUI 진단 패널에 뜸):
- `inverted_filler_model`: 혼합 재료의 모델이 역산 때와 다름.
- `inverted_filler_fraction`: 분율이나 `fraction` 변수 범위가 [0.5φ₀, min(1, 1.5φ₀)] 밖(상대 허용치 1e-9).
- `inverted_filler_direct`: 역산 재료를 층, 층 재료 후보, 혼합의 매트릭스로 직접 사용.
- 함께 고침: `_conductive`가 Re ε ≤ 0인 재료를 전도성에서 빠뜨려 퍼콜레이션 경고가 사라지던 문제.

**GUI**: 재료 관리자의 "Invert filler…" 대화상자가 같은 판정과 경고를 씁니다(`inversion.diagnostics`, `warning_flags`, 개발 이력 3.31). 노트에 넣는 이름의 `;`는 `,`로 바꿉니다. 이름이 `model=`·`fraction=`을 흉내 내면 출처를 잘못 읽기 때문입니다.

**비구형 충전재 (v9)**: `--model odelevskiy`는 `--shape-n`과 `--percolation`이 필수이고 다른 모델에는 줄 수 없습니다. 함량은 임계값보다 작아야 합니다. 노트에 `n=…; pc=…;`가 더해지고, 혼합 재료의 N이나 pc가 다르면 `inverted_filler_model` 경고가 납니다. 식과 근거는 개발 이력 3.32에 있습니다.

**미룬 것**: 여러 함량 CSV의 동시 역산. 표를 평활화하거나 Debye로 맞추면 φ₀에서의 재현이 깨지므로 기본값으로 하지 않습니다.

**Argon 리뷰**: 지적 14개를 코드와 실험으로 확인해 대부분 반영했습니다. 답변의 Bruggeman 미분 공식은 계수가 틀려(3이 아니라 9) 중앙차분과 대조해 고쳤습니다.

### 13.10 (v8) FSS 격자 치수에서 L·C: `fss-grid`
조밀한 금속 메시와 패치 배열은 치수에서 L·C를 해석적으로 구할 수 있습니다(Luukkonen 2008, 식 3·4·5·6·8·9). 계산은 `fss.py`(Qt 없음)에 있고 치수는 저장하지 않습니다. L·C가 최적화로 바뀌는 순간 치수와 어긋나기 때문이며, 일회성 계산기이므로 파일 형식은 바뀌지 않습니다.

- **식**: 메시 L = μ₀D/(2π)·ln(1/sin(πw/(2D)))(w: 스트립 폭, ε_eff와 무관), 패치 C = (2ε₀ε_eff D/π)·ln(1/sin(πw/(2D)))(w: 패치 사이 **간격**). 각도 계수는 메시 `L_TM`, 패치 `C_TE` = −1/(2ε_eff).
- **명령**: `coating-cli fss-grid --pattern {mesh,patch} --period-mm D (--strip-width-mm W | --gap-mm G) --eps-eff E`. 메시는 스트립 폭, 패치는 간격만 받습니다. 플래그를 나눈 이유: 패치 폭을 간격 자리에 넣어도 `0 < w < D`를 통과해 C가 150배 틀리기 때문입니다. 값에 기본값이 없고, 잘못된 값은 `bound`와 같이 usage(종료 2)입니다.
- **결과**: `L_h`, `C_f`(해당 없으면 null), `angle`, `period_m`, `width_m`, `eps_eff`, `width_ratio`, `caution_limit_hz`, `dense_limit_hz`, `sheet`(명세 단위의 조각), `assumptions`. `sheet`는 `{"L_nh", "C_pf": null, "angle"}`(메시) 또는 `{"L_nh": 0, "C_pf", "angle"}`(패치)로, 순수한 메시·패치를 뜻합니다. `model`과 `R_ohm`은 사용자가 정합니다. 식은 이상 도체 기준이므로 R을 지어내지 않습니다. `width_ratio > 0.5`면 경고 `wide_geometry`.
- **유효 한계**: `dense_limit_hz` = 0.5·c/(D√ε_eff), `caution_limit_hz` = 0.3·c/(D√ε_eff). 식 4의 조건은 k_eff D ≪ 2π이므로 k_eff D = 2π를 한계로 쓰면 회절 로브를 놓칩니다(D = 10 mm, ε_r = 4에서 k_eff D = 2π는 19 GHz, 기판 로브는 0°에서 15 GHz). ε_eff = (ε_r+1)/2이면 √(2ε_r+2) ≥ √ε_r+1이므로 0.5 한계는 어느 각도의 로브보다도 낮습니다. 0.3은 경험적 기준입니다.
- **가정**: 정사각 격자, 이상 도체, 주축 평면 입사, w ≪ D, 두꺼운 유전체에서의 ε_eff.
- **GUI**: RLC 시트 속성의 "From grid dimensions…". 치수는 프로젝트의 두께 단위로 받고, 기본 적용은 시트를 순수하게 만듭니다(메시: C 제거, 패치: L = 0, 다른 쪽 계수 제거). 남은 소자가 있으면 메시의 리액턴스 부호까지 뒤집히기 때문입니다. "Keep the other element"로 유지할 수 있습니다. 스윕과 활성 목표의 최대 주파수를 한 번만 비교합니다. 새 값이 기존 L·C 변수 범위 밖이면 범위 재설정을 제안합니다(기본 켬). 그대로 두면 최적화기가 시작값을 범위 안으로 잘라 치수에서 얻은 값을 잃습니다.
- **한계**: 패치의 C는 ε_eff에 비례하지만, 적용 뒤 패널에서 ε_eff를 바꾸면 각도 계수만 바뀝니다. 스트립 배열(식 10·11)은 프리셋 되짚기에서 패치와 구별되지 않아 넣지 않았습니다.

### 13.11 (v10) 여러 함량에서 Odelevskiy 비율: `fit-shape`
Odelevskiy 규칙(13.9 "비구형 충전재")의 N과 pc를 측정에서 정하는 명령입니다. 계산은 `materials/shape_fit.py`(Qt 없음)에 있고, 근거와 수치는 개발 이력 3.34에 있습니다.

- **정해지는 것은 B = N/pc 하나입니다.** y = e_h/(e_i − e_h)로 쓰면 e = e_h + e_h·p/(u − B·p), u = N + y입니다. 충전재가 주파수마다 자유로운 표이면 N은 u에 흡수되므로, 어느 함량의 측정으로도 N과 pc를 따로 정할 수 없습니다. B가 같은 두 (N, pc)는 둘 다 표를 만들 수 있는 한 모든 함량에서 같은 값을 예측합니다.
- **N은 판정을 바꿉니다.** 역산의 차폐 좌표가 x = N/u이므로, 같은 B에서도 N이 크면 `outside_model`로 거부될 수 있습니다(예: 매트릭스 3, 복합재 5 − 0.1j, 함량 0.1, B = 0.5에서 N = 0.15는 통과하고 0.25·0.5는 거부). 그래서 기본 (N, pc)를 내지 않고, 시편마다 `invert-filler`가 받아들이는 N 범위를 보고합니다.
- **맞춤**: 주파수마다 u 하나를 감쇠 Gauss-Newton으로 구하고(시작값은 가중 선형 최소제곱 해, 비용이 줄 때만 받아들임), B는 [1e-4, (1 − 1e-6)/max p]의 로그 격자 200점에서 고른 뒤 이웃 구간에서 Brent로 다듬습니다. 잔차는 시편·채널마다 max|e_k|로 나눈 값이고(`fit`, `invert-filler`의 rms와 같은 정규화), `rms`는 쓰인 모든 (채널, 시편, 주파수) 잔차의 rms입니다. 복합재가 모든 함량에서 매트릭스와 같은 채널(비자성 μ = 1)은 빼고 해당 rms를 null로 둡니다.
- **평탄 구간**: 최소점을 포함하는 연결 구간 중 rms ≤ max(1.1·rms_min, rms_min + 1e-4)인 곳(끝은 log B에서 선형 보간). 잡음 수준을 모르므로 신뢰구간이 아닙니다. 함량이 2개면 하나를 빼는 교차 검증이 불가능해 쓰지 않습니다.
- **허용 N**: 시편마다 (B·max p, min(B, 1)) 안 400점에서 pc = min(N/B, 1)로 `invert_filler`를 실제로 돌려 `ok`인 점의 최소·최대와 비율(`admissible_share`)을 냅니다. 끝값은 실제로 통과한 점이라 그대로 `invert-filler`에 넣을 수 있습니다. 구간 안에 거부되는 점이 섞일 수 있어 비율을 함께 봅니다.
- **명령**: `coating-cli fit-shape --composite CSV FRACTION --composite CSV FRACTION [...] (--matrix-csv F | --matrix-eps RE LOSS [--matrix-mu RE LOSS]) [--weight-fractions --density-filler R --density-matrix R]`
  - 함량 2개 이상, 서로 달라야 하고(1e-9), 같은 CSV를 두 번 줄 수 없습니다. `--weight-fractions`를 주면 두 밀도가 필수이고, 주지 않으면 밀도를 받지 않습니다. 결과의 `fraction`은 늘 부피 분율입니다. 이름은 `invert-filler`의 값을 받는 `--fraction-wt`와 겹치지 않게 했습니다.
  - 격자는 첫 시편의 주파수 중 모든 입력(시편, 매트릭스 CSV)이 덮는 점이고, 나머지는 보간합니다. 2점 미만이면 `invalid_value`(3). 출력 파일과 저널은 없습니다.
- **경고**: `shape_fit_poor`(rms > 0.10, 규칙이 이 복합재 계열을 설명하지 못할 수 있음), `shape_at_bound`(B가 탐색 범위 끝), `shape_flat`(평탄 구간 끝이 B의 0.5배 미만이나 1.5배 초과), `shape_two_fractions`(함량 2개: 남는 검사가 없음), `shape_no_admissible_n`(그 시편에서 허용 N이 없음).
- **사용 흐름**: B와 허용 N 범위를 사용자에게 보여 주고, N은 사용자가 형상 정보로 정합니다(편상의 감자 계수 등). 그다음 `invert-filler --model odelevskiy --shape-n N --percolation N/B --validate …`로 표를 만들고 다른 함량으로 검증합니다. 맞춤이 좋다는 것은 측정한 함량 사이의 예측이 된다는 뜻이지 충전재 모양의 증거가 아닙니다(Bruggeman으로 만든 데이터도 rms 0.08~1.5 %로 맞음).
- **범위 밖**: 공동 맞춤 표를 파일로 쓰기(어느 함량도 정확히 재현하지 않아 출처·왕복 검사와 맞지 않음), N·pc의 최적화 변수화, GUI.

### 13.12 (v11) 2포트 측정에서 물성 추출: `extract-nrw`
- **`coating-cli extract-nrw S2P --thickness-mm D -o OUT.csv [--force] [--cutoff-ghz FC | --waveguide-a-mm A] [--branch N] [--offset1-mm L1] [--offset2-mm L2]`**
- 시편이 선로 단면을 채운 동축선·자유공간(TEM, 기본) 또는 직사각 도파관(TE10, 차단 주파수 `--cutoff-ghz` 또는 넓은 벽 `--waveguide-a-mm`에서 c/2a)의
  Touchstone v1 2포트 파일을 받습니다. S 파라미터는 빈 선로의 파동 임피던스로 정규화되고(TRL 교정처럼) 기준면이 시편 양면에 있어야 합니다.
  기준면이 시편 앞뒤의 빈 선로에 있으면 `--offset1-mm`·`--offset2-mm`로 옮깁니다. S21과 S12는 평균합니다.
- `materials/extraction.nrw`(Nicholson-Ross 1970, Weir 1974): K = (S11² − S21² + 1)/(2S11), Γ = K ∓ √(K² − 1)(|Γ| ≤ 1), T = (S11 + S21 − Γ)/(1 − (S11 + S21)Γ),
  1/Λ = ln(1/T)/(j2πd)(T의 위상을 주파수를 따라 펼침), μ = (1/Λ)(1 + Γ)/((1 − Γ)√(1/λ₀² − 1/λc²)), ε = λ₀²/μ·(1/λc² + 1/Λ²). e^{+jωt} 규약.
- **위상 가지**: T의 위상은 2πn까지만 정해집니다. 최저 주파수에서 `--branch`(기본 0, 시편이 반파장보다 얇을 때)에서 시작해 펼칩니다.
  측정 군지연 −d(arg T)/dω(n과 무관)와 추출한 εμ가 예측하는 지연(n에 따라 다름)을 비교하고, 결과가 수동인 가지를 우선해 `suggested_branch`를 냅니다.
  강한 분산(공진 근처)에서는 지연 비교가 근사입니다.
- **결과**: `output_path`, `n_points`, `data_range_hz`, `line`(`TEM`/`TE10 waveguide`), `cutoff_hz`, `thickness_m`, `branch`, `suggested_branch`,
  `delay_mismatch`(중앙값 상대 차), `reciprocity_error`, `reference_ohm`(파일의 R, 정보용), `resonant_points`. 출력 CSV는 측정 CSV 형식이라
  명세의 `{"name", "csv"}`, `fit`, `invert-filler`에 그대로 씁니다.
- **경고**: `half_wave_resonance`(|S11| < 0.05: 시편이 반파장의 배수에 가까워 값이 불안정), `branch_suspect`(제안 가지가 다름, `--branch`로 다시),
  `nonpassive`(이득이 나온 주파수), `nonreciprocal`(|S21 − S12|/|S21| > 0.05, 교정 확인). 입력 파일은 `--force`로도 덮어쓰지 않습니다.
- **GUI**(3.46): 재료 관리자 → 새로 만들기 → "S 파라미터(.s2p)에서 추출…"(`gui/dialogs/nrw.py`). 같은 `nrw`를 부르고 같은 경고를 보이며,
  제안 가지가 다르면 "가지 n 쓰기" 버튼을 냅니다. 두께·도파관 치수·밀도는 빈 칸에서 시작합니다(값을 지어내지 않음).
- **불확도**(3.47): `--uncertainty-csv U.csv`와 `--thickness-sigma-mm`·`--mag-sigma-db`·`--phase-sigma-deg`(1σ, 기본 0 = 없음; 하나 이상 필요),
  `--uncertainty-samples N`(기본 200), `--seed`. `materials/extraction.nrw_uncertainty`가 몬테카를로로 ε′, ε″, μ′, μ″의 주파수별 표준편차를 구해
  `f [GHz],u(eps'),u(eps''),u(mu'),u(mu'')` CSV로 씁니다. 두께 오차는 표본마다 하나(계통), S 파라미터의 크기·위상 오차는 점마다 독립(잡음)입니다.
  교정 드리프트처럼 주파수에 매끄러운 오차는 이 모델에 없어, 잡음 추정이지 교정 불확도 전체가 아닙니다. 결과의 `uncertainty`에 표본 수, 시드,
  ε′·μ′의 중앙값 상대 불확도, 입력 σ가 들어갑니다(끈 경우 null).
- **비자성 맞춤**(3.50): `--method nonmagnetic`은 μ = 1로 두고 주파수마다 복소 ε를 S11·S21에 최소제곱으로 맞춥니다(미지수 실수 2개, 측정 실수 4개;
  NIST 반복법의 발상). 첫 주파수는 NRW 값에서, 이후는 앞 주파수의 해에서 시작합니다. 저손실 시편의 반파장 공진에서 NRW보다 훨씬 안정합니다.
  맞춤 잔차가 0.02를 넘으면 경고 `fit_poor`(자성 시편일 수 있음). 결과의 `method`, 불확도도 같은 방법을 반복합니다. GUI 대화상자에도 "방법"이 있습니다.
- **위치 불변 비자성 맞춤**(3.54): `--method nonmagnetic-invariant --holder-length-mm L_AIR [--holder-sigma-mm S]`. 시편이 홀더 안 어디에 있는지 몰라도 됩니다.
  E1 = S11·S22 − S21·S12와 E2 = (S21 + S12)/2는 빈 선로 전체 길이 L_air − d에만 의존하므로(NIST TN 1355), 이를 빈 선로만큼 되돌려 μ = 1의 ε에 맞춥니다(절대 잔차).
  시작값도 위치 불변입니다: S11s² = E1 + S21s²의 두 부호로 NRW를 돌려 μ가 1에 가까운 쪽을 씁니다. 시편은 대칭이어야 하며 |S11|, |S22| 차가 0.05를 넘으면 경고
  `asymmetric`. `--offset`과 함께 쓸 수 없고, 불확도에는 `--holder-sigma-mm`(표본마다 하나)가 더해집니다. 결과의 `holder_length_m`. GUI 대화상자의 방법에도 있습니다.
- **동축 공기 틈 보정**(3.51): `--coax-gap R1 R2 R3 R4`(mm: 내도체, 시편 구멍, 시편 바깥, 외도체 반지름)로 지름 방향 층 모델의 보정을 적용합니다
  (ε: 직렬 정전 용량 εc = εm·L2/(L3 − εm·L1), μ: 인덕턴스 합 μc = (μm·L3 − L1)/L2; L1 = ln(R2/R1) + ln(R4/R3), L2 = ln(R3/R2), L3 = ln(R4/R1)).
  복소값에 적용하므로 손실도 보정되고, 불확도 표본에도 같은 보정이 들어갑니다. 도파관과 함께 쓰면 `usage`, Re(L3 − εm·L1) ≤ 0.1·L3이면(틈에 비해 ε가 큼)
  보정이 불안정해 `invalid_value`입니다. 결과의 `coax_gap_mm`.
- **범위 밖**: 교정 불확도(계통 오차) 전파, GUI의 불확도와 공기 틈 보정.

### 13.13 (v12) 여러 함량에서 GEM의 pc·t: `fit-gem`
- **`coating-cli fit-gem --composite CSV FRACTION ... (--matrix-csv F | --matrix-eps RE LOSS [--matrix-mu RE LOSS]) [--weight-fractions --density-filler R --density-matrix R]`**
  (입력 규칙은 `fit-shape`와 같음).
- **식**: 충전재는 주파수마다 자유로운 복소값입니다. x = ε^(1/t), a = εₘ^(1/t), A = (1 − pc)/pc, R = (1 − φ)(a − x)/(a + A x)이면 함량마다
  b = εᵢ^(1/t) = x(φ − R A)/(φ + R)가 닫힌 꼴로 나옵니다. 주파수마다 함량별 b를 가중치 1/(|∂b/∂e| s_k)²로 평균해(1차 근사의 상대 잔차 최소화) 충전재를 정하고,
  모든 함량을 순방향 GEM으로 예측한 상대 rms(함량마다 max_f |e_k|로 정규화)가 비용입니다. ε와 μ에 같은 (pc, t)를 씁니다(혼합 재료와 같음).
- **탐색**: pc 로그 격자 0.005–0.6(40점) × t 1–4(31점), 가장 낮은 격자점 5곳에서 경계 있는 Nelder–Mead. 평탄 영역은 rms ≤ max(1.1·최소, 최소 + 1e-4)이고
  최적 격자점과 4방향으로 이어진 점들의 범위에 최적값을 더한 것입니다(신뢰구간이 아님).
- **결과**: `percolation`, `exponent`, `rms`, `rms_per`, `channels_used`, `flat_region {percolation, exponent}`, `search_range`, `per_composite[]`.
- **경고**: `gem_one_sided`(모든 함량이 최적 pc의 한쪽), `gem_fit_poor`(rms > 0.10), `gem_at_bound`, `gem_two_fractions`, `gem_t_weak`(평탄 t 폭 ≥ 1.5),
  `gem_channel_mismatch`(ε·μ 단독 맞춤의 pc가 격자 한 칸 여유를 두고도 겹치지 않음).
- **사용 흐름**: `fit-gem` → `invert-filler --model gem --percolation PC --exponent T`(한 복합재에서 닫힌 꼴로 역산, 차폐 좌표 −R/φ, 해석적 증폭 계수,
  모델 비교 상대는 Bruggeman, 임계값 위 함량도 역산·예측 가능) → `--validate`로 다른 함량 확인 → 같은 `percolation`·`exponent`의 GEM 혼합 재료.
- **범위 밖**: 충전재 역산 GUI 대화상자의 GEM, `fit-gem`의 GUI.

## 부록 A. (v5) 재료 dict 형식 (`.coat`·명세 공통, SI, 접미사 없음)
모든 종류 공통: `kind`, `name`, `density`(kg/m³, 혼합 재료에는 없음 — 성분에서 계산), `note`.

| `kind` | 필드 | 의미 |
|---|---|---|
| `constant` | `eps_re`, `eps_loss`, `mu_re`, `mu_loss` | ε = eps_re − j·eps_loss, μ도 같음(손실 > 0). 주파수와 무관 |
| `dispersive` | `eps_inf`, `eps_loss`, `sigma`(S/m), `eps_terms[]`, `mu_inf`, `mu_loss`, `mu_terms[]` | ε = eps_inf − j·eps_loss − jσ/(ωε₀) + Σ 항. 항은 `{"type": "debye", "delta", "f0"}`, `{"type": "lorentz", "delta", "f0", "gamma"}`(Hz) 또는 `{"type": "havriliak_negami", "delta", "f0", "alpha", "beta"}`(스키마 12) — Debye Δ/(1 + j f/f₀), Lorentz Δ·f₀²/(f₀² − f² + j f γ), Havriliak-Negami Δ/(1 + (j f/f₀)^α)^β(0 < α, β ≤ 1, 범위 밖은 `check`의 `hn_exponent`) |
| `tabulated` | `f[]`(Hz), `eps_re[]`, `eps_loss[]`, `mu_re[]`, `mu_loss[]`(없으면 μ = 1), `source` | 측정값. 범위 밖은 외삽하지 않고 오류 |
| `mixture` | `matrix`, `inclusion`(재료 이름), `fraction`(0~1, 부피 분율), `model`(`"maxwell_garnett"`, `"bruggeman"`, `"odelevskiy"`(+ `shape_n`, `percolation`) 또는 `"gem"`(+ `percolation` 0~1, `exponent` 0~10, 스키마 13)) | 2성분 유효 매질. 성분은 다른 혼합 재료여도 됨(순환 금지). GEM은 McLachlan의 일반 유효 매질 식으로 퍼콜레이션 전후가 연속이며 pc = 1/3, t = 1이면 Bruggeman. `invert-filler`·`fit-shape`는 GEM을 받지 않음 |
| `uniaxial` | `inplane`, `normal`(등방성 재료 이름) | 일축 이방성(축 = 층의 법선, 스키마 11). ε = diag(ε∥, ε∥, ε⊥), μ도 같음. 수직 입사는 `inplane`만 보고, `normal`은 사입사에서 작용(TE는 μ⊥, TM은 ε⊥). 밀도는 `inplane`의 밀도. 혼합 재료의 성분·다른 일축 재료의 성분·입사 매질이 될 수 없음(`check`의 `uniaxial_misuse`, 풀이 시 `invalid_value`·`solver_error`) |

측정 CSV는 재료 dict 대신 명세에서 `{"name", "csv", "density"?, "note"?}`로 씁니다(13.2절).

(v6) **측정 CSV 형식**(`materials/csvio.py`): 쉼표·세미콜론·탭·공백 구분, `#`으로 시작하는 줄은 주석.
- 열: `x, eps', eps'', [mu', mu'']`(기본) 또는 헤더에 loss tangent를 쓰면 `x, eps', tan d, [mu', tan d]`. 손실은 양수(공학 규약). μ 열이 없으면 μ = 1.
- 첫 열(`x`)의 단위는 첫 헤더 칸으로 정합니다: `Hz`/`kHz`/`MHz`/`GHz`/`THz`(헤더가 없으면 GHz), 파장(`nm`, `um`, `mm` …), 파수(`cm-1`).
- 굴절률 형식 `x, n, k`도 읽습니다(μ = 1, 헤더에 `n`, `k` 필요). 형식 오류는 `invalid_spec`(`details.csv_error`).

## 부록 B. (v6) 명령별 출력 예시 (`result` 부분)
모든 명령은 4.1절의 봉투(`ok`, `command`, `cli_schema`, `app_version`, `input`, `result`, `warnings`, `stopped`, 실패 시 `error`) 안에 아래 `result`를 넣습니다.
숫자는 예시입니다. **키 이름과 구조는 규약**이며, 테스트가 실제 출력과 키 구조를 비교합니다(9절 10i).

**공통 정의**
- `worst_rl_db`: 목표의 주파수 × 각도 × 편광 격자에서 가장 나쁜(가장 큰) RL [dB, 내부 부호, 음수가 좋음].
- **`margin_db = worst_rl_db − goal_db`.** 0 이하면 목표 충족, 양수면 그만큼(dB) 미달. 여러 목표의 최댓값이 `max_margin_db`입니다.
- 파라미터 값 객체(`ParamValue`): `{"value": 0.00195, "unit": "m", "display_value": 1.95, "display_unit": "mm"}` (+ 무게 분율이면 `"value_wt"`).

`bound`
```json
{"f_hz": [8e9, 12e9], "goal_db": -15, "required_mu_d_m": 0.001093,
 "mu_s": 1.0, "min_thickness_m": 0.001093, "assumptions": ["normal incidence", "PEC backing", "air incident"]}
```

`materials`
```json
{"materials": [{"name": "Epoxy", "kind": "constant", "note": "representative resin", "is_demo": true,
                "dict": {"kind": "constant", "name": "Epoxy", "density": 1200.0, "note": "representative resin",
                         "eps_re": 3.6, "eps_loss": 0.07, "mu_re": 1.0, "mu_loss": 0.0},
                "params": [{"path": ["eps_re"], "label": "eps'", "unit": ""}], "static_mu": 1.0}]}
```

`check`
```json
{"valid": true, "counts": {"error": 0, "warning": 1, "info": 2},
 "issues": [{"level": "info", "code": "demo_values", "material": "Epoxy", "target": null, "args": {}, "message": "..."}],
 "limits": [{"target": 0, "target_name": "X 0-30", "required_mu_d_m": 0.001093, "design_mu_d_m": 0.003,
             "max_achievable_mu_d_m": 0.004, "status": "ok", "note": "normal-incidence condition only"}],
 "optimization": {"n_vars": 2, "n_combos": 1, "estimated_max_evals": 4530}}
```

`solve --targets --summary-only`
```json
{"sweep": "freq",
 "summary": {"best": {"TE": {"rl_db": -4.2, "f_hz": 8.96e9}, "TM": {"rl_db": -4.2, "f_hz": 8.96e9}, "avg": {"rl_db": -4.2, "f_hz": 8.96e9}},
             "total_thickness_m": 0.003, "areal_mass_kg_m2": 4.1},
 "targets": [{"index": 0, "name": "X 0-30", "goal_db": -15, "worst_rl_db": -2.06, "margin_db": 12.94}],
 "max_margin_db": 12.94}
```

`optimize -o OUT.coat --restarts 3`
```json
{"message": "converged", "n_evals": 4086, "elapsed_s": 2.4, "seed_used": 1234567,
 "targets": [{"index": 0, "name": "X 0-30", "goal_db": -15, "worst_rl_db": -6.37, "margin_db": 8.63}],
 "max_margin_db": 8.63,
 "terms": {"objective": 0.42, "worst_db": -6.37, "margin_db": 8.63, "mean_r": 0.05, "thickness_m": 0.00195, "mass_kg_m2": 2.6},
 "values": [{"path": ["layer", "<uid>", "thickness"], "label": "L1 Absorber: thickness", "layer": "Absorber",
             "before": {"value": 0.003, "unit": "m", "display_value": 3.0, "display_unit": "mm"},
             "after": {"value": 0.00195, "unit": "m", "display_value": 1.95, "display_unit": "mm"},
             "at_bound": null}],
 "choices": [],
 "restarts": [{"seed": 1234567, "objective": 0.42, "max_margin_db": 8.63}, {"seed": 1234568, "objective": 0.47, "max_margin_db": 9.1}],
 "history": [[150, 3.1], [900, 0.6]], "output_path": "s1_opt.coat"}
```
`at_bound`는 `"lower"`/`"upper"`/`null` — 변수가 범위 끝(범위 폭의 0.1% 안)에 붙었는지(플레이북 4단계의 판단 근거).
(구현 후 추가, 실제 CLI 블라인드 테스트 반영) `result.terms`에 `thickness_max_m`, `thickness_at_limit`(총 두께가 `thickness_max`에 걸림 —
이때 개별 층은 보통 자기 범위 끝에 있지 않음), `result.run_settings`(`maxiter`, `popsize`, `polish` — 이번 실행에만 적용, 결과 파일에 저장하지 않음),
`best_seed`(보고한 설계를 만든 시드). 실험 기록에도 `best_seed`를 남깁니다.
(v12) 명세의 `optimization.robust_samples`(정수 0~1000, 0 = 끔)·`robust_quantile`(0 초과 1 이하, 기본 0.8)로 강건 모드를 켭니다(3.44).
최악값 항이 공차 설정에서 뽑은 고정 표본 K개의 표본별 최대 여유의 `robust_quantile` 분위수가 됩니다(국소 정밀화는 그 위쪽 꼬리의 평균).
켜면 `result.terms`에 `robust_margin_db`(그 분위수; ≤ 0이면 그 비율 이상의 표본이 모든 목표를 만족)와 `sample_yield`(최적화기 자기 표본에서의 통과 비율)가
붙습니다. `sample_yield`는 같은 표본에 맞춘 값이라 낙관적입니다. 수율은 `tolerance --angle-grid`로 따로 확인합니다.

`tolerance --corners --target-db -15` (`--angle-grid`면 `angle_mode: "grid"`, 행은 격자 각도마다, `note`는 "angle grid only; …", `--n-angle`을 주면 `n_angle`)
```json
{"angle_mode": "corners", "n_samples": 200, "seed_used": 1, "target_db": -15,
 "corners": [{"target": 0, "target_name": "X", "angle_deg": 0, "pol": "TE", "target_db": -15, "n_samples": 200, "yield_fraction": 0.17,
              "worst_db": {"min": -16.0, "median": -13.5, "max": -10.2}},
             {"target": 0, "target_name": "X", "angle_deg": 30, "pol": "TE", "target_db": -15, "n_samples": 200, "yield_fraction": 0.01,
              "worst_db": {"min": -15.1, "median": -11.9, "max": -9.0}}],
 "joint_yield_fraction": 0.01, "min_corner": {"target": 0, "angle_deg": 30, "pol": "TE"},
 "note": "corners only; angles inside each target's range are not sampled"}
```
최상위 `target_db`는 `--target-db` 값이며, 없으면 `null`이고 행마다 그 목표의 `goal_db`가 `target_db`입니다.
`--corners` 없이: `{"scope": {"angle_deg": 0, "pol": "avg"}, "n_samples", "seed_used", "yield_fraction", "target_db", "lower_pct", "upper_pct", "yield_intervals_hz", "worst_db": {...}, "data"?: {...}}` + 경고 `single_angle_yield`.

`spec FILE.coat` (`-o` 없음)
```json
{"spec": {"spec_version": 1, "name": "...", "layers": [], "...": "13.2절 형식 전체"}}
```
`-o OUT.json`이면 `{"output_path": "OUT.json"}`이고 파일에는 봉투 없는 명세만 씁니다.

`journal DIR`
```json
{"n_trials": 9, "fingerprints": [{"spec_fingerprint": "a1b2c3", "targets": [{"name": "X 0-30", "goal_db": -15}],
   "thickness_max_m": 0.004, "n_trials": 7,
   "best": {"seq": 6, "max_margin_db": 1.0, "snapshot": "snapshots/9f8e7d6c5b4a.coat", "note": "2-layer graded"}}],
 "trials": [{"seq": 1, "command": "solve", "note": "baseline", "max_margin_db": 12.94, "exit_code": 0, "snapshot": "snapshots/..."}],
 "warnings": ["targets changed during the run (2 fingerprints)"]}
```

`fit CSV --mu-debye 1`
```json
{"material": {"kind": "dispersive", "name": "CI sheet fit", "eps_inf": 14.2, "eps_loss": 0.4, "sigma": 0.0, "eps_terms": [],
              "mu_inf": 1.0, "mu_loss": 0.0, "mu_terms": [{"type": "debye", "delta": 2.8, "f0": 2.1e9}], "density": 1000.0, "note": "fitted: ci_sheet.csv, 1-8 GHz"},
 "rms_eps": 0.012, "rms_mu": 0.031, "data_range_hz": [1e9, 8e9]}
```

`invert-filler comp.csv -o filler.csv --model bruggeman --fraction 0.2 --density-filler 7800 --matrix-eps 3 0.03`
```json
{"output_path": "filler.csv", "material": {"name": "filler", "csv": "/abs/filler.csv", "density": 7800.0, "note": "inverted: comp.csv; model=bruggeman; fraction=0.2; matrix=eps 3-0.03j"},
 "fraction": 0.2, "model": "bruggeman", "n_points": 171, "data_range_hz": [1e9, 18e9],
 "amplification": {"eps": {"median": 6.1, "max": 9.4}, "mu": {"median": 3.2, "max": 5.0}},
 "ill_conditioned_points": 0, "negative_real_points": 0, "gain_points": 0, "outside_model_points": 0, "branch_points": 0, "clamped_points": 0, "roundtrip_max": 3e-15,
 "prediction": {"at_fractions": [0.1, 0.3], "fraction_sensitivity": {"rms_eps": 0.05, "rms_mu": 0.04},
                "model_disagreement": {"rms_eps": 0.08, "rms_mu": 0.03}, "model_disagreement_reason": null},
 "validation": [{"csv": "comp30.csv", "fraction": 0.3, "n_points": 171, "rms_eps": 0.02, "rms_mu": 0.03}]}
```

`fit-shape --composite c05.csv 0.05 --composite c10.csv 0.1 --composite c15.csv 0.15 --matrix-eps 3 0.05`
```json
{"n_over_pc": 0.4, "rms": 5.7e-10, "channels_used": ["eps"], "n_points": 40, "data_range_hz": [1e9, 18e9],
 "search_range": [1e-4, 6.66666], "flat_interval": [0.4, 0.4015],
 "profile": {"n_over_pc": [1e-4, "…200 values"], "rms": [0.71, "…"]},
 "per_composite": [{"csv": "c05.csv", "fraction": 0.05, "rms_eps": 7.5e-10, "rms_mu": null,
                    "shape_n_range": [0.0608, 0.1643], "percolation_range": [0.152, 0.411], "admissible_share": 0.307}]}
```

`fss-grid --pattern patch --period-mm 5 --gap-mm 0.5 --eps-eff 2.2`
```json
{"pattern": "patch", "period_m": 0.005, "width_m": 0.0005, "eps_eff": 2.2, "width_ratio": 0.1, "L_h": null, "C_f": 1.15e-13,
 "angle": {"C_TE": -0.2273}, "caution_limit_hz": 1.21e10, "dense_limit_hz": 2.02e10,
 "sheet": {"L_nh": 0.0, "C_pf": 0.115, "angle": {"C_TE": -0.2273}},
 "assumptions": ["dense square lattice", "ideal conductors", "incidence in a principal plane", "width or gap much smaller than the period", "eps_eff = (eps_r + 1)/2 needs a dielectric thick compared with the period"]}
```
