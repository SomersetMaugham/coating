# 계획 v4 — Agent Friendly CLI 어댑터

작성: 2026-11-07 · 브랜치 `agent-cli` · 상태: **v4 (Argon 2차 리뷰 반영, 구현 전)**
- v1 → v2: 1차 Argon 리뷰 반영(12.1·12.2절).
- v2 → v3: 목표 워크플로우를 "에이전트가 사용자의 현재 조성에서 출발해 목표에 도달할 때까지 스스로 실험한다"로 정하고,
  설계 명세(`build`/`spec`), 실험 기록(`--journal`), 물리 한계 검사(Rozanov), 에이전트 플레이북, 연결 방식 비교를 추가(13절).
- v3 → v4: 2차 Argon 리뷰 반영(12.3절). 명세를 `Project` 전체를 담도록 확장, Rozanov 적용 조건·정적 투자율 계산·판정 수준 수정,
  실험 기록의 비교 기준·시드 기록 추가, 연결 방식을 **CLI + Skill/플레이북**으로 결정. 바뀐 곳에는 "(v3)"·"(v4)"를 붙였습니다.

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
- `result`: `message`, `n_evals`, `elapsed_s`(=`res.elapsed`), `terms`(`res.terms.as_dict()`, `res.terms`가 `None`이면 `null`),
  `values[]`(`path`, `label`, `before`, `after` — 4.1절 형식), `choices[]`(`uid`, `layer`, `before`, `after`), `history`(`[[n_evals, best], …]`), `output_path`.
  `before`는 `apply_result()`를 부르기 **전에** 기록합니다.
- 유효한 설계를 못 찾으면(`terms is None`, `message == "no valid design found"`) `ok:false`, `solver_error`류가 아니라 `no_valid_design`(종료 4), 파일은 쓰지 않습니다.
- 중단(5절)이면 `stopped: true`, 종료 코드 5. `-o`가 있으면 부분 결과도 저장합니다(결과에 `stopped`를 적어 구분).

### `coating-cli tolerance FILE [--seed N] [--n-samples N] [--target-db G] [--angle-deg X] [--pol TE|TM|avg] [--samples]`
- 격자는 `tolerance_frequencies(p)`, 수율 기준 대역은 `yield_intervals(p)` (GUI와 같음).
- `result`: `n_samples`, `yield_fraction`, `target_db`, `lower_pct`, `upper_pct`, `yield_intervals_hz`, `worst_db`의 통계(`min`, `median`, `max`),
  `data`(같은 길이의 1차원 배열만: `f_hz`, `nominal_db`, `median_db`, `lower_db`, `upper_db`). `--summary-only` 지원.
- 표본별 `worst_db` 전체는 `--samples`일 때만 넣습니다.
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
11. **리팩터링 회귀**: 기존 `test_optimize_tolerance.py`, `test_gui_smoke.py`, `test_i18n.py` 그대로 통과. `preflight`가 GUI 대화상자와 같은 오류·경고 목록을 냄.
    새 `_ISSUES_EN` 문구(`material_cycle`)의 KO 항목 존재.

게이트: `QT_QPA_PLATFORM=offscreen python -m pytest` (CI 3 OS × Python 3.10/3.13).

## 10. 커밋 계획

1. **엔진 리팩터링·수정** (6절): 옮긴 함수, `preflight`, `NewerSchemaError`·`source_schema`, `check_material` 순환 처리, `validate_settings`의 `KeyError`,
   단위 환산표, i18n 문구(+KO). GUI는 새 위치를 import. 엔진 단위 테스트 추가. 기존 테스트 통과.
2. **CLI 추가** (`cli/`, `pyproject.toml`, `tests/test_cli.py`) — 1~7절의 명령.
3. (v3) **에이전트 실험 루프** — `limits.py`(+단위 테스트), `cli/spec.py`·`build`·`spec`, `cli/journal.py`·`--journal`·`journal`, `bound`, `check`의 `limits`.
4. (v4) **플레이북과 연결** — `docs/AGENT_PLAYBOOK.md`, `.claude/skills/coating-experiment/SKILL.md`, `AGENTS.md` 단락(13.6절). MCP 코드는 넣지 않음.
5. **문서**: README(영·한)에 CLI 절, AGENTS.md "Commands"에 `coating-cli` 추가, `DEVELOPMENT_HISTORY.md`에 기록.

`.coat` 저장 형식은 바뀌지 않으므로 `SCHEMA_VERSION`은 올리지 않습니다(`source_schema`는 저장하지 않는 속성).
커밋 1에 GUI 화면 문구 변화는 없습니다(`unknown_material`은 기존 문구와 같고, `material_cycle`은 지금까지 예외로 나던 경우에만 보임).
그래도 2.1절 6단계에 따라 영문·한글 진단 패널을 오프스크린으로 한 번 캡처해 확인합니다.

## 11. 남은 열린 질문

v1의 Q1~Q7은 모두 결정했습니다(12.2절). 새로 남은 질문입니다.
- **N1** GUI 진단 패널도 혼합물 성분까지 펼쳐 검사하게 할지(7절 `check` 3번). 이번 범위에서는 CLI만 넓히는 안.
- **N2** `optimize`가 `no_valid_design`일 때 종료 코드 4가 맞는지(설정은 유효하지만 모든 평가가 실패한 경우).
- N3~N6은 v4에서 결정했습니다(12.4절).

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
| N4 사입사 목표 | 수직 입사 값은 참고로만, 판정은 `unknown`, 실패 없음 | 한계식이 수직 입사·PEC에서 유도됨 |
| N5 기록 스냅숏 | 내용 해시 이름의 전체 사본(`snapshots/<sha>.coat`) | 재구성 로직 없이 GUI로 바로 열림, 같은 내용은 한 번만 저장 |
| N6 단위 표기 | 키 접미사, 필드당 하나로 고정. 변수 범위는 `range` + `unit`(확인용) | 숫자를 문자열 파싱 없이 다룸, 스키마가 하나 |

검증하지 못한 주장: Argon은 "agy도 작업공간의 `SKILL.md`를 읽는다"고 했지만 확인하지 못했습니다. 그래서 agy 쪽은 `AGENTS.md` 단락에만 의존합니다.

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
    {"name": "CB 20%", "kind": "mixture", "matrix": "Epoxy", "inclusion": "Carbon black",
     "fraction": 0.20, "model": "bruggeman"},
    {"name": "Measured CI", "csv": "data/ci_measured.csv"}
  ],
  "layers": [
    {"name": "R-card", "sheet": {"model": "constant", "R_ohm": 377, "X_ohm": 0}},
    {"name": "Absorber", "material": "CB 20%", "thickness_mm": 1.5}
  ],
  "sweep": {"f_ghz": [2, 18], "n_f": 401, "log_f": false, "angle_deg": 0, "f_at_ghz": 10,
            "angle_range_deg": [0, 80], "n_angle": 81, "map_n_f": 161, "map_n_angle": 61},
  "targets": [
    {"name": "X", "f_ghz": [8, 12], "n_f": 41, "angle_deg": [0, 30], "n_angle": 4,
     "pols": ["TE", "TM"], "goal_db": -20, "enabled": true}
  ],
  "variables": [
    {"layer": "Absorber", "param": "thickness", "range": [0.5, 3.0], "unit": "mm"},
    {"material": "CB 20%", "param": ["fraction"], "range": [0.10, 0.40], "unit": "frac"},
    {"layer": "R-card", "param": "R", "range": [100, 1000], "unit": "ohm"}
  ],
  "choices": [{"layer": "Absorber", "candidates": ["CB 20%", "Measured CI"]}],
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
- **변수 범위**는 `{"range": [lo, hi], "unit": "<표시 단위>"}`입니다. `unit`은 그 파라미터의 `param_unit()`(`mm`, `ohm`, `nH`, `pF`, `GHz`, `S/m`, `frac`, `""`)과
  **같아야 하며**, 다르면 `invalid_spec`입니다(에이전트가 단위를 잘못 짐작하는 것을 잡기 위한 확인용 필드).
- **시트 층**: `{"model": "constant", "R_ohm", "X_ohm"}` 또는 `{"model": "rlc", "R_ohm", "L_nh", "C_pf"}`. `model`은 필수(`constant`와 `L=0, C=None`인 `rlc`를 구분하기 위해).
- **뒷판**: `"pec"` 또는 `{"kind": "halfspace", "material": "<이름>"}`.
- **목표**: `angle_deg`의 상한이 하한보다 크면 `n_angle`이 필수이고 2 이상이어야 합니다. 빠지면 `invalid_spec` —
  `BandTarget.n_angle` 기본값이 1이라 그대로 두면 `grid()`가 하한 각도만 평가합니다(`project.py:102-110`).
- **재료 dict는 `.coat`와 같은 형식(SI, 접미사 없음)**이라는 예외를 명시합니다. `Material.to_dict()` 그대로이며(`density` kg/m³, `sigma` S/m, 분산 항의 `f0`·`gamma` Hz),
  단위 접미사 규칙은 재료 dict 바깥에만 적용합니다. 측정 CSV는 `{"name", "csv", "density"?, "note"?}`(명세 파일 기준 상대 경로, `materials/csvio.load_csv`).
- **내장 재료**: `build`는 `Project()`의 내장 재료에서 시작합니다. 명세에 같은 이름이 있으면 덮어쓰고, `"remove_builtin": ["PTFE", …]`로 지울 수 있습니다.
  `spec`은 `m.to_dict() == builtin.to_dict()`(note 포함, `Air` 포함)인 재료만 생략하고, 지워진 내장 재료는 `remove_builtin`에 적습니다.
  (`is_builtin_demo()`는 `Air`를 데모로 보지 않고 note를 무시하므로 이 판정에 쓰지 않습니다 — `checks.py:31-42`.)
- **혼합 재료는 2성분**(매트릭스 + 충전재 하나)입니다. 3성분 이상은 혼합 재료를 중첩해 표현하며, 플레이북에 분율의 의미(바깥 혼합 기준)를 적습니다.
  내장 `"Carbonyl iron / epoxy"`는 이미 복합재이므로 다시 에폭시에 섞으면 "희석"이라는 점도 플레이북에 적습니다.
- 생략한 섹션은 `Project` 기본값을 씁니다. 단 **`targets`를 생략하면 목표 없음**으로 둡니다(기본 8–12 GHz 목표를 쓰지 않음) —
  의도하지 않은 목표로 최적화하는 일을 막기 위해서입니다(`optimize`는 `invalid_optimization_settings`로 거부).
- `build SPEC -o OUT.coat`: 검증 → `Project` 조립 → 저장. 명세 오류는 `invalid_spec`(종료 3, `details.path`에 JSON 경로, 예: `layers[1].thickness_mm`).
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
  - 이슈는 **둘 다 경고 수준**입니다: `rozanov_limit`(violated), `rozanov_infeasible`(infeasible). 오류로 두면 의욕적인 목표만으로 `check`가 실패(종료 4)하는데,
    도달할 수 없는 목표도 "최선의 RL을 찾는" 정상 사용입니다(예: `cara` 예제는 −20 dB 기본 목표에 −14.6 dB까지). 판단은 플레이북의 멈춤 규칙이 합니다.
  - **사입사(N4)**: 목표의 각도 범위가 0°를 포함하면 수직 입사 값을 계산하되 `note`에 "수직 입사 기준 참고값"이라 적고, `violated`/`infeasible`이어도 `unknown`으로 낮춥니다.
    0°를 포함하지 않는 목표는 `unknown`입니다. 사입사 목표로 `check`가 실패하는 일은 없습니다.
  - 중복 제거 키는 `(code, material, target index, message)`입니다 — 목표가 여럿이면 `rozanov_*` 이슈가 하나로 합쳐지지 않게.
- `bound --f-ghz LO HI --goal-db G [--mu-s M]`: 파일 없이 필요한 `μs·d`와 `μs = M`일 때 최소 두께를 냅니다(공기 입사, PEC 전제를 결과에 명시). `"input": null`.
- 테스트: 위 수치(1.457 mm), 재료 종류별 `static_permeability`(상수 손실·Tabulated → `None`, Debye·Lorentz → `mu_inf + Σ delta`, MG/Bruggeman 혼합),
  Salisbury 예제가 `ok`, 한계보다 얇은 단일층이 `violated`, 두께 상한이 낮으면 `infeasible`, 재료 후보에 고투자율 재료를 넣으면 `infeasible`이 풀림, halfspace 뒷판이 `unknown`.
- 새 이슈 코드 `rozanov_limit`·`rozanov_infeasible`은 `_ISSUES_EN`에 넣고 KO 항목도 추가합니다(GUI 진단에는 이번에 연결하지 않음).

### 13.5 에이전트 플레이북
툴 사용법과 별개로 **실험 루프의 절차와 멈춤 규칙**을 문서로 둡니다: `docs/AGENT_PLAYBOOK.md`(영어, 에이전트가 읽는 문서).
1. 입력 확인: 사용자 설명에서 층·재료·배합비·두께·목표를 뽑고, 빠진 값은 **추측하지 말고 묻습니다**.
   재료가 내장 데모 값(`demo_values` 이슈)이면 "실측 데이터가 아니므로 결과는 참고용"이라고 반드시 알립니다.
2. `bound`로 목표의 현실성 확인 → `build` → `check`. 오류면 고칩니다. `rozanov_infeasible`이면 사용자에게 목표·두께 상한 조정이나 고투자율 재료 추가를 제안하고 멈춥니다.
3. `solve --summary-only --journal DIR`로 기준선을 기록합니다(목표가 있으면 margin이 함께 기록됨).
4. 변수·범위 설정 → `optimize --journal DIR`. 목표별 `margin_db`를 보고 다음 수를 정합니다.
   - **탐색용 시도는 작게**: `--maxiter 40 --timeout 60`. 재료 후보(choices)는 조합 수만큼 실행 시간이 곱해지므로(조합 ≤ 64면 조합마다 DE 전체 실행)
     `info`·`check`가 보여 주는 `n_combos`와 `estimated_max_evals`를 먼저 봅니다. 최종 후보만 기본 설정으로 다시 돌립니다.
   - **두께 상한으로 목표를 맞출 때는 `w_thickness = 0`**: 두께 항이 RL과 맞바꿔져 목표 전에 멈추는 것을 막습니다. 두께를 줄이는 것이 목표일 때만 쓰고, 그때는 `thickness_max`와 함께 씁니다.
   - 모든 margin ≤ 0: 5단계로.
   - 두께 변수가 상한에 붙음: 상한 완화를 사용자에게 제안하거나 고투자율 재료·층 추가를 검토합니다.
   - 특정 대역만 미달: 층 추가(Jaumann형), 저항 시트 삽입, 재료 후보 추가를 검토합니다(`spec` → 명세 수정 → `build`).
5. `tolerance --target-db <목표 goal_db> --journal DIR`로 수율 확인(공차 설정의 기본 `target_db`는 −10 dB라 목표와 다를 수 있음). 낮으면 결과에 위험을 명시합니다.
6. 멈춤 규칙: 목표 충족 + 수율 기준 충족 / 시도 예산(기본 20회 또는 사용자가 정한 값) 소진 / 같은 목표에서 연속 3회 개선 없음 / `rozanov_infeasible`.
7. 보고: `journal DIR` 요약 + 최종 설계의 명세(`spec`) + `seed_used`(재현용) + 남은 위험(데모 재료, 수율, 사입사 근사).

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
