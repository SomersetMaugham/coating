"""Korean catalogue.  Keys are the English source strings used in the code."""

KO = {
    # material issues
    "Measured data covers {lo:.4g}-{hi:.4g} GHz but {flo:.4g}-{fhi:.4g} GHz is requested.":
        "측정 데이터 범위는 {lo:.4g}–{hi:.4g} GHz인데 {flo:.4g}–{fhi:.4g} GHz가 요청되었습니다.",
    "References a material that does not exist: {ref}.": "존재하지 않는 재료를 참조합니다: {ref}.",
    "Passivity: eps'' < 0 (gain) near {f:.4g} GHz.": "수동성 위반: {f:.4g} GHz 부근에서 ε″ < 0 (이득 매질).",
    "Passivity: mu'' < 0 (gain) near {f:.4g} GHz.": "수동성 위반: {f:.4g} GHz 부근에서 μ″ < 0 (이득 매질).",
    "eps_inf = {value:.3g} < 1 is unusual for a real dielectric.":
        "ε∞ = {value:.3g} < 1 은 실제 유전체로는 드문 값입니다.",
    "Snoek limit: delta_mu x f0 = {product:.3g} GHz exceeds ~{limit:.3g} GHz (pure-iron bound); "
    "this permeability is probably not manufacturable.":
        "Snoek 한계: Δμ × f0 = {product:.3g} GHz 가 약 {limit:.3g} GHz(순철 기준 상한)를 넘습니다. "
        "실제로 제조하기 어려운 투자율일 가능성이 큽니다.",
    "A dispersion term has a negative strength, frequency or damping.":
        "분산 항의 세기·주파수·감쇠 중 음수 값이 있습니다.",
    "eps' up to {value:.3g} is unusually large.": "ε′ 최대 {value:.3g} 은(는) 비정상적으로 큰 값입니다.",
}

KO.update({
    # ---- menus & actions -------------------------------------------------------
    "&File": "파일(&F)", "&Edit": "편집(&E)", "&View": "보기(&V)", "&Analysis": "해석(&A)", "&Help": "도움말(&H)",
    "&New": "새로 만들기(&N)", "&Open…": "열기(&O)…", "&Save": "저장(&S)", "Save &As…": "다른 이름으로 저장(&A)…",
    "&Quit": "종료(&Q)", "&Undo": "실행 취소(&U)", "&Redo": "다시 실행(&R)", "&Materials…": "재료(&M)…",
    "&Preferences…": "환경 설정(&P)…", "&About Coating Studio": "Coating Studio 정보(&A)",
    "Physics &conventions": "물리 규약(&C)", "Physics conventions": "물리 규약",
    "Open &example": "예제 열기(&E)", "Open &recent": "최근 파일(&R)", "Clear list": "목록 지우기",
    "(no recent files)": "(최근 파일 없음)", "Export &figure…": "그래프 내보내기(&F)…",
    "Export &data (CSV)…": "데이터 내보내기(&D) (CSV)…", "Run &optimisation": "최적화 실행(&O)",
    "S&top optimisation": "최적화 중지(&T)", "Run &tolerance analysis": "공차 분석 실행(&T)",
    "Main toolbar": "기본 도구 모음", "New project": "새 프로젝트", "Open a project": "프로젝트 열기",
    "Save the project": "프로젝트 저장", "Export the current plot (PNG/SVG/PDF)": "현재 그래프 내보내기 (PNG/SVG/PDF)",
    "Open the material manager": "재료 관리자 열기",
    "Start the optimisation with the current settings": "현재 설정으로 최적화 시작",
    "About Coating Studio": "Coating Studio 정보",
    "<h3>Coating Studio {v}</h3><p>Multilayer coating simulator and optimiser — v1 focuses on microwave and "
    "radar absorbers.</p><p>Transmission-line (impedance) recursion for planar stacks, oblique TE/TM incidence, "
    "dispersive and measured materials, effective-medium mixtures, differential-evolution optimisation and "
    "Monte-Carlo tolerance analysis.</p><p>MIT License.</p>":
        "<h3>Coating Studio {v}</h3><p>다층 코팅 시뮬레이터 겸 최적화 도구입니다. v1은 마이크로파·레이더 "
        "전파 흡수체에 초점을 맞춥니다.</p><p>평면 다층 구조의 전송선(임피던스) 재귀 해석, TE/TM 사입사, "
        "분산·측정 재료, 실효 매질 혼합, 차분 진화 최적화, 몬테카를로 공차 분석을 제공합니다.</p>"
        "<p>MIT 라이선스.</p>",
    "<b>Time convention</b>: e<sup>+jωt</sup>; ε = ε′ − jε″, μ = μ′ − jμ″ (ε″, μ″ &gt; 0 are lossy).<br>"
    "<b>Reflection loss</b>: RL = 20·log₁₀|Γ| (negative dB; −10 dB ≈ 90% absorbed). The display sign can be "
    "changed in Preferences.<br><b>Γ</b> is the reflection coefficient of the tangential electric field.<br>"
    "<b>Layer order</b>: the top row of the layer stack faces the incident wave.<br><b>TE</b>: E perpendicular "
    "to the plane of incidence; <b>TM</b>: H perpendicular. Average = unpolarised power average.<br>"
    "<b>Resistive sheet</b>: shunt impedance Zs = R + jX in Ω/sq (free space ≈ 376.7 Ω/sq), or a series RLC "
    "circuit Zs = R + jωL + 1/(jωC) (inductive X &gt; 0). The RLC values are normal-incidence lumped values used "
    "for every angle and polarisation - valid for sub-wavelength unit cells below the grating-lobe onset.<br>"
    "<b>Units</b>: GHz, mm, degrees, S/m, g/cm³; the engine works in SI.":
        "<b>시간 규약</b>: e<sup>+jωt</sup>; ε = ε′ − jε″, μ = μ′ − jμ″ (ε″, μ″ &gt; 0 이면 손실).<br>"
        "<b>반사손실</b>: RL = 20·log₁₀|Γ| (음수 dB, −10 dB ≈ 90% 흡수). 표시 부호는 환경 설정에서 바꿀 수 "
        "있습니다.<br><b>Γ</b>는 접선 방향 전기장의 반사계수입니다.<br><b>층 순서</b>: 층 스택의 맨 위 행이 "
        "입사파를 마주합니다.<br><b>TE</b>: 전기장이 입사면에 수직, <b>TM</b>: 자기장이 입사면에 수직. "
        "평균 = 비편광 전력 평균.<br><b>저항 시트</b>: 병렬 임피던스 Zs = R + jX [Ω/sq] (자유공간 ≈ 376.7 Ω/sq) "
        "또는 직렬 RLC 회로 Zs = R + jωL + 1/(jωC) (유도성 X &gt; 0). RLC 값은 수직 입사 기준의 집중 소자 "
        "값으로 모든 입사각과 편광에 그대로 쓰이며, 단위 셀이 파장보다 충분히 작고 회절 로브가 생기기 전까지 "
        "유효합니다.<br><b>단위</b>: GHz, mm, 도, S/m, g/cm³ (엔진 내부는 SI 단위).",

    # ---- main window -----------------------------------------------------------
    "Untitled": "제목 없음", "Layer stack": "층 스택", "Properties": "속성", "Analysis settings": "해석 설정",
    "Diagnostics": "진단", "Frequency": "주파수", "Angle": "입사각", "Map": "맵", "Smith chart": "Smith 차트",
    "Absorption": "흡수 분해", "Material data": "재료 물성", "Optimisation": "최적화", "Tolerance": "공차 분석",
    "Cannot compute: {e}": "계산할 수 없습니다: {e}",
    "Thickness {t} mm": "두께 {t} mm", "Areal mass {m} kg/m²": "면밀도 {m} kg/m²",
    "Best RL {v} dB at {f} GHz": "최적 RL {v} dB @ {f} GHz",
    "No problems found in the materials used.": "사용 중인 재료에서 문제가 발견되지 않았습니다.",
    "Save changes to “{n}”?": "“{n}”의 변경 내용을 저장할까요?",
    "Stop the running optimisation first.": "실행 중인 최적화를 먼저 중지하세요.",
    "Open project": "프로젝트 열기", "Cannot open project": "프로젝트를 열 수 없습니다",
    "Opened {p}": "열었습니다: {p}", "Save project": "프로젝트 저장",
    "Cannot save project": "프로젝트를 저장할 수 없습니다", "Saved {p}": "저장했습니다: {p}",
    "The new language will be used after a restart.": "새 언어는 다시 시작한 뒤 적용됩니다.",
    "An optimisation is running. Stop it and quit?": "최적화가 실행 중입니다. 중지하고 종료할까요?",
    "Salisbury screen": "Salisbury 스크린", "Dallenbach layer": "Dallenbach 층",
    "Two-layer Jaumann": "2층 Jaumann 흡수체", "Ferrite tile": "페라이트 타일",
    "Carbon / epoxy mixture": "카본/에폭시 혼합 층",

    # ---- layer stack & properties ----------------------------------------------
    "Add slab layer": "슬래브 층 추가", "Add resistive sheet": "저항 시트 추가", "Duplicate layer": "층 복제",
    "Delete layer": "층 삭제", "Move towards front (incident side)": "앞쪽(입사면 쪽)으로 이동",
    "Move towards back": "뒤쪽으로 이동", "Layer": "층", "Material / sheet": "재료 / 시트",
    "Thickness / R": "두께 / R", "Front (incident side) at the top, backing at the bottom.":
        "위가 앞면(입사면), 아래가 뒷면입니다.",
    "Slab": "슬래브", "Resistive sheet": "저항 시트", "Sheet": "시트", "Reorder layers": "층 순서 변경",
    "PEC": "PEC(금속)", "half-space": "반무한 매질", "Total {t} mm": "총 {t} mm",
    "Selected layer": "선택한 층", "Name": "이름", "optional": "선택 사항", "Material": "재료",
    "Edit…": "편집…", "Thickness": "두께", "Resistance R": "저항 R", "Reactance X": "리액턴스 X",
    "Opt.": "최적화",
    "Include this value in the optimisation (bounds are set in the Optimisation panel).":
        "이 값을 최적화 변수에 포함합니다(범위는 최적화 탭에서 설정).",
    "Material candidates (optimisation)": "재료 후보 (최적화)",
    "Let the optimiser choose this layer's material": "최적화가 이 층의 재료를 고르도록 함",
    "Select a layer to edit its properties.": "속성을 편집할 층을 선택하세요.",
    "Boundaries": "경계 조건", "Lossless medium the wave arrives from": "전파가 들어오는 무손실 매질",
    "Incident medium": "입사 매질", "Metal plate (PEC)": "금속 뒷판 (PEC)",
    "Semi-infinite medium": "반무한 매질", "Backing": "뒷면", "Backing medium": "뒷면 매질",
    "Density {rho} g/cm³ · areal mass {m} kg/m²": "밀도 {rho} g/cm³ · 면밀도 {m} kg/m²",
    "Material not found": "재료를 찾을 수 없습니다",
    "Free-space impedance is 376.7 Ω/sq.": "자유공간 임피던스는 376.7 Ω/sq 입니다.",
    "Rename layer": "층 이름 변경", "Change layer material": "층 재료 변경", "Change thickness": "두께 변경",
    "Change sheet resistance": "시트 저항 변경", "Change sheet reactance": "시트 리액턴스 변경",
    "Toggle optimisation variable": "최적화 변수 설정 변경", "Toggle material choice": "재료 선택 설정 변경",
    "Change material candidates": "재료 후보 변경", "Change incident medium": "입사 매질 변경",
    "Change backing": "뒷면 변경", "thickness": "두께", "volume fraction": "체적 분율",
    "ε″ (constant)": "ε″ (상수)", "μ″ (constant)": "μ″ (상수)",

    # ---- sweep panel -----------------------------------------------------------
    "Frequency sweep": "주파수 스윕", "Start": "시작", "Stop": "중지", "End": "끝", "Points": "점 개수",
    "Logarithmic frequency axis": "로그 주파수 축", "Incidence angle": "입사각", "Angle sweep": "입사각 스윕",
    "From": "시작", "To": "끝", "Frequency × angle map": "주파수 × 입사각 맵",
    "Frequency points": "주파수 점 개수", "Angle points": "각도 점 개수",

    # ---- plots -----------------------------------------------------------------
    "Reflection loss [dB] (higher is better)": "반사손실 [dB] (높을수록 우수)",
    "Reflection loss [dB] (lower is better)": "반사손실 [dB] (낮을수록 우수)",
    "Reflectance |Γ|²": "반사율 |Γ|²", "Absorptance": "흡수율", "Transmittance": "투과율",
    "Average": "평균", "Show": "표시", "−10 dB line": "−10 dB 기준선", "Frequency [GHz]": "주파수 [GHz]",
    "Incidence {a}°": "입사각 {a}°", "f = {f} GHz, value = {v}": "f = {f} GHz, 값 = {v}",
    "Incidence angle [°]": "입사각 [°]", "f = {f} GHz": "f = {f} GHz",
    "θ = {a}°, value = {v}": "θ = {a}°, 값 = {v}", "Polarisation": "편파",
    "−10 / −20 dB contours": "−10 / −20 dB 등고선",
    "10 / 20 dB contours": "10 / 20 dB 등고선", "10 dB line": "10 dB 기준선",
    "Incidence angle of the frequency sweep. Also used by the Smith chart and absorption tabs.":
        "주파수 스윕의 입사각입니다. Smith 차트와 흡수 분해 탭에도 쓰입니다.",
    "Frequency of the angle sweep.": "입사각 스윕의 주파수입니다.", "Incidence": "입사각",
    "Show or hide the diagnostics panel": "진단 패널 보이기/숨기기",
    "No problems": "문제 없음", "1 problem": "문제 1개", "{n} problems": "문제 {n}개",
    "1 note": "참고 1개", "{n} notes": "참고 {n}개",
    # independent loss tolerances
    "Permittivity ε′": "유전율 ε′", "Dielectric loss ε″": "유전 손실 ε″", "Permeability μ′": "투자율 μ′",
    "Magnetic loss μ″": "자성 손실 μ″", "Follow ε′": "ε′ 연동", "Follow μ′": "μ′ 연동",
    "Scale the loss with the same factor as the real part (fixed tan δ) instead of varying it independently.":
        "손실을 독립적으로 바꾸지 않고 실수부와 같은 비율로 바꿉니다(tan δ 고정).",
    "ε″ and μ″ vary independently of ε′ and μ′, so the loss tangent varies too. A relative tolerance has no "
    "effect where the nominal loss is zero.":
        "ε″과 μ″은 ε′, μ′과 독립적으로 변하므로 손실 탄젠트(tan δ)도 함께 변합니다. 공칭 손실이 0이면 상대 "
        "공차는 효과가 없습니다.",
    # RLC sheets
    "Model": "모델", "Constant (R + jX)": "상수 (R + jX)", "Series RLC": "직렬 RLC", "RLC sheet": "RLC 시트",
    "Inductance L": "인덕턴스 L", "Capacitance C": "커패시턴스 C", "none": "없음",
    "Change sheet model": "시트 모델 변경", "Change sheet inductance": "시트 인덕턴스 변경",
    "Change sheet capacitance": "시트 커패시턴스 변경", "Toggle sheet capacitor": "시트 커패시터 켜기/끄기",
    "Inductive grid (no resonance)": "유도성 격자 (공진 없음)", "Capacitive, no resonance": "용량성 (공진 없음)",
    "f₀ = {f} GHz · Q = {q}": "f₀ = {f} GHz · Q = {q}", "f₀ = {f} GHz": "f₀ = {f} GHz",
    "Zs({f} GHz) = {z} Ω/sq": "Zs({f} GHz) = {z} Ω/sq",
    "f₀ is outside the frequency sweep.": "f₀가 주파수 스윕 범위 밖에 있습니다.",
    "Series RLC sheet: R {r} Ω/sq, L {l} nH, C {c}": "직렬 RLC 시트: R {r} Ω/sq, L {l} nH, C {c}",
    "Capacitor on/off. Without a capacitor the sheet is an inductive grid (R + jωL).":
        "커패시터 켜기/끄기. 커패시터가 없으면 유도성 격자(R + jωL)가 됩니다.",
    "Series RLC: Zs = R + jωL + 1/(jωC), the equivalent circuit of a patterned (circuit-analog / FSS) layer. "
    "The circuit values are normal-incidence lumped values used for every angle and polarisation - valid for "
    "sub-wavelength unit cells.":
        "직렬 RLC: Zs = R + jωL + 1/(jωC), 패턴 층(회로 등가형 / FSS)의 등가회로입니다. 회로 값은 수직 입사 "
        "기준의 집중 소자 값으로 모든 입사각과 편광에 그대로 쓰이며, 단위 셀이 파장보다 충분히 작을 때 유효합니다.",
    "Circuit-analog absorber (RLC sheet)": "회로 등가 흡수체 (RLC 시트)",
    # optimisation targets (spec mask)
    "Targets": "목표", "Band preset": "대역 프리셋", "pts": "점",
    "Goal RL (≤)": "목표 RL (≤)", "Goal RL (≥)": "목표 RL (≥)",
    "Include this target in the optimisation": "이 목표를 최적화에 포함합니다",
    "Each row is one requirement; the optimiser minimises the worst margin (worst RL minus goal) over "
    "the enabled rows.":
        "각 행이 요구 조건 하나입니다. 최적화기는 켜진 행들 가운데 가장 나쁜 마진(최악 RL − 목표)을 "
        "최소화합니다.",
    "Show the optimisation targets whose angle range includes the current incidence angle (goal level "
    "over their band)":
        "현재 입사각을 포함하는 최적화 목표를 표시합니다(대역에 걸친 목표 수준)",
    "Target {n}: {s}": "목표 {n}: {s}", "met (margin {m} dB)": "만족 (마진 {m} dB)",
    "missed by {m} dB": "{m} dB 부족",
    "Dual-band Jaumann (X + Ku, oblique)": "이중 대역 Jaumann (X + Ku, 경사 입사)",
    # reference traces
    "&Pin reference": "비교 곡선 고정(&P)", "References": "비교 곡선", "References ({n})": "비교 곡선 ({n})",
    "Reference {n}": "비교 곡선 {n}", "Before optimisation": "최적화 전", "(measured)": "(측정)",
    "Import measured curve": "측정 곡선 가져오기", "Import measured curve…": "측정 곡선 가져오기…",
    "Remove all references": "모든 비교 곡선 지우기", "Rename reference": "비교 곡선 이름 바꾸기",
    "Rename…": "이름 바꾸기…", "Remove": "제거", "No references yet": "비교 곡선이 아직 없습니다",
    "Pin the current design as a reference curve on the Frequency, Angle and Smith chart tabs":
        "현재 설계를 비교 곡선으로 고정해 주파수·입사각·Smith 차트 탭에 함께 표시합니다",
    "Show a measured reflection-loss curve (CSV) on the Frequency tab":
        "측정한 반사손실 곡선(CSV)을 주파수 탭에 표시합니다",
    "Show, hide, rename or remove reference curves": "비교 곡선을 보이기·숨기기·이름 바꾸기·제거합니다",
    "All {n} reference slots are in use; remove one first.": "비교 곡선 {n}개 자리가 모두 찼습니다. 하나를 먼저 제거하세요.",
    "The design before optimisation was not pinned: all {n} reference slots are in use.":
        "비교 곡선 {n}개 자리가 모두 차서 최적화 전 설계를 고정하지 못했습니다.",
    "Pinned “{name}”. It follows the current sweep settings.":
        "“{name}”을(를) 고정했습니다. 현재 스윕 설정에 맞춰 다시 계산됩니다.",
    "Imported “{name}” (read as positive return loss).": "“{name}”을(를) 가져왔습니다(양수 반사손실로 읽음).",
    "Imported “{name}” (read as 20·log₁₀|Γ|, negative = good).":
        "“{name}”을(를) 가져왔습니다(20·log₁₀|Γ|, 음수일수록 우수로 읽음).",
    "Some references cannot be computed for the current settings: {items}":
        "일부 비교 곡선은 현재 설정에서 계산할 수 없습니다: {items}",
    "f = {f} GHz, θ = {a}°, RL = {v} dB": "f = {f} GHz, θ = {a}°, RL = {v} dB",
    "Γ locus over the frequency sweep; ● start, ■ stop": "주파수 스윕에 따른 Γ 궤적 (● 시작, ■ 끝)",
    "Γ = {g}, z = {z}": "Γ = {g}, z = {z}", "Transmitted": "투과", "Reflected": "반사",
    "Fraction of incident power": "입사 전력 대비 비율", "Permittivity": "유전율", "Permeability": "투자율",
    "Cannot draw this plot: {err}": "그래프를 그릴 수 없습니다: {err}", "Export figure": "그래프 내보내기",
    "Export failed": "내보내기 실패", "Export data": "데이터 내보내기",
    "This view has no data to export.": "이 화면에는 내보낼 데이터가 없습니다.",

    # ---- optimisation ----------------------------------------------------------
    "Target band": "목표 대역", "Frequency from": "주파수 시작", "to": "끝", "Angle from": "입사각 시작",
    "Objective (weighted, normalised terms)": "목적함수 (정규화 항목의 가중합)", "Term": "항목",
    "Weight": "가중치", "Reference": "기준값", "Worst-case RL in band": "대역 내 최악 RL",
    "Mean reflectance |Γ|²": "평균 반사율 |Γ|²", "uses the RL reference": "RL 기준값 사용",
    "Total thickness": "총 두께", "Areal mass": "면밀도", "Thickness limit": "두께 상한",
    "Each term is divided by its reference so weights are comparable; RL is in dB (negative = good).":
        "각 항목을 기준값으로 나눠 가중치를 서로 비교할 수 있게 합니다. RL은 dB 단위입니다(음수일수록 우수).",
    "Each term is divided by its reference so weights are comparable; RL is in dB (positive = good).":
        "각 항목을 기준값으로 나눠 가중치를 서로 비교할 수 있게 합니다. RL은 dB 단위입니다(양수일수록 우수).",
    "Variables": "변수", "Parameter": "파라미터", "Current": "현재값", "Lower": "하한", "Upper": "상한",
    "Add": "추가", "(missing) ": "(없음) ", "Remove variable": "변수 제거",
    "Layer {i}: {n} candidates": "{i}층: 후보 {n}개",
    "Material choices: {parts} — {n} combinations": "재료 선택: {parts} — 조합 {n}개",
    "Material choices: none (enable per layer in the Properties panel).":
        "재료 선택: 없음 (속성 패널에서 층별로 켤 수 있습니다).",
    "Algorithm": "알고리즘", "random": "무작위", "Local refinement (L-BFGS-B)": "국소 정밀화 (L-BFGS-B)",
    "Generations (max)": "최대 세대 수", "Population factor": "개체군 배수", "Random seed": "난수 시드",
    "Global search: differential evolution. Material choices with ≤ {n} combinations are enumerated "
    "exhaustively.": "전역 탐색은 차분 진화(DE)입니다. 재료 조합이 {n}개 이하이면 모든 조합을 전수 탐색합니다.",
    "Run optimisation": "최적화 실행", "Ready.": "준비됨.", "Best design": "최적 설계", "Item": "항목",
    "Value": "값", "Apply to project": "프로젝트에 적용", "Open as new project": "새 프로젝트로 열기",
    "Change variable bound": "변수 범위 변경", "Add optimisation variable": "최적화 변수 추가",
    "Remove optimisation variable": "최적화 변수 제거",
    "Cannot start optimisation": "최적화를 시작할 수 없습니다", "Unknown material: {n}": "알 수 없는 재료: {n}",
    "Pre-flight check failed": "사전 검증 실패", "Pre-flight check": "사전 검증",
    "The following warnings were found:": "다음 경고가 발견되었습니다:", "Run anyway?": "그래도 실행할까요?",
    "Starting…": "시작하는 중…", "Stopping…": "중지하는 중…", "global search": "전역 탐색",
    "local refinement": "국소 정밀화", ", combination {i}/{n}": ", 조합 {i}/{n}",
    "{stage}{combo} · iteration {it} · evaluations {ev} · best objective {b}":
        "{stage}{combo} · 반복 {it} · 평가 {ev}회 · 최적 목적값 {b}",
    "No valid design found.": "유효한 설계를 찾지 못했습니다.", "Stopped by user": "사용자가 중지함",
    "Finished": "완료", "{msg} · {ev} evaluations in {t} s": "{msg} · {t}초 동안 {ev}회 평가",
    "Optimisation finished: worst-case RL {v} dB": "최적화 완료: 대역 내 최악 RL {v} dB",
    "Optimisation failed.": "최적화에 실패했습니다.", "Optimisation failed": "최적화 실패",
    "Objective": "목적함수 값", "Layer {i} material": "{i}층 재료",
    "Apply optimisation result": "최적화 결과 적용", "Cannot apply result": "결과를 적용할 수 없습니다",
    "The project changed since the run started: {e}": "실행을 시작한 뒤 프로젝트가 바뀌었습니다: {e}",
    "Optimisation result applied (Undo restores the previous design).":
        "최적화 결과를 적용했습니다 (실행 취소로 이전 설계를 되돌릴 수 있습니다).",
    "{name} (optimised)": "{name} (최적화)", "Objective evaluations": "목적함수 평가 횟수",
    "Best objective": "최적 목적값", "Convergence": "수렴 곡선",

    # ---- tolerance -------------------------------------------------------------
    "Run the analysis to see the spread of reflection loss.": "분석을 실행하면 반사손실의 분포가 표시됩니다.",
    "{a:g}–{b:g} percentile band": "{a:g}–{b:g} 백분위 구간", "Median": "중앙값",
    "Nominal design": "공칭 설계", "Target": "목표", "Yield {y:.1f}% ({n} samples)": "수율 {y:.1f}% (표본 {n}개)",
    "Monte-Carlo settings": "몬테카를로 설정", "Normal (value = 1σ)": "정규분포 (값 = 1σ)",
    "Uniform (± value)": "균일분포 (± 값)", "Samples": "표본 수", "Distribution": "분포",
    "Default tolerances (relative)": "기본 공차 (상대값)", "Permittivity ε": "유전율 ε",
    "Permeability μ": "투자율 μ", "Sheet impedance": "시트 임피던스",
    "Per-layer tolerances (%)": "층별 공차 (%)", "Blank cells use the default tolerance.":
        "빈 칸은 기본 공차를 사용합니다.", "Evaluation": "평가", "Custom yield band": "수율 대역 직접 지정",
    "Target RL (≤)": "목표 RL (≤)", "Band from": "대역 시작",
    "Yield = share of samples whose worst RL in the band meets the target. "
    "Without a custom band, the bands of the enabled optimisation targets are used.":
        "수율 = 대역 내 최악 RL이 목표를 만족하는 표본의 비율입니다. 대역을 직접 지정하지 않으면 "
        "켜진 최적화 목표들의 대역을 사용합니다.",
    "Target RL (≥)": "목표 RL (≥)",
    "Run analysis": "분석 실행", "Change layer tolerance": "층 공차 변경",
    "Tolerance analysis: yield {y:.1f}% of {n} samples": "공차 분석: 표본 {n}개 중 수율 {y:.1f}%",
    "Tolerance analysis failed": "공차 분석 실패",

    # ---- materials dialog --------------------------------------------------------
    "Constant": "상수", "Dispersive model": "분산 모델", "Measured data": "측정 데이터",
    "Mixture (EMA)": "혼합 (실효 매질)", "Type": "종류", "Debye": "Debye", "Lorentz": "Lorentz",
    "Debye term": "Debye 항", "Lorentz term": "Lorentz 항", "Remove term": "항 제거", "Materials": "재료",
    "New": "새로 만들기", "Import measured CSV…": "측정 CSV 가져오기…", "Duplicate": "복제", "Delete": "삭제",
    "Library": "라이브러리", "Import materials from library file…": "라이브러리 파일에서 재료 가져오기…",
    "Export all materials to library file…": "모든 재료를 라이브러리 파일로 내보내기…", "General": "일반",
    "Density": "밀도", "Note": "메모",
    "Changes apply immediately and can be undone with Ctrl+Z in the main window. Loss uses the convention "
    "ε = ε′ − jε″ (ε″ > 0 is lossy).":
        "변경 내용은 즉시 적용되며 기본 창에서 Ctrl+Z로 되돌릴 수 있습니다. 손실 규약은 ε = ε′ − jε″ "
        "(ε″ > 0 이면 손실)입니다.",
    "tan δ = ε″/ε′ (or μ″/μ′); editing it keeps the real part. Refractive index N = n − jk = √(εμ); "
    "editing n or k sets ε = N²/μ and keeps μ.":
        "tan δ = ε″/ε′ (또는 μ″/μ′)이며, 바꾸면 실수부는 그대로 둡니다. 굴절률 N = n − jk = √(εμ)이며, "
        "n이나 k를 바꾸면 μ는 그대로 두고 ε = N²/μ로 설정합니다.",
    "Loss tangent is only defined when the real part is positive.": "손실 탄젠트는 실수부가 양수일 때만 정의됩니다.",
    "Built-in demonstration values (representative, not a datasheet). Use measured data for a real design.":
        "기본 제공 시연용 값입니다(대표값이며 데이터시트 값이 아님). 실제 설계에는 측정 데이터를 쓰세요.",
    "Constant complex ε and μ": "상수 복소 ε, μ", "Permittivity ε(f)": "유전율 ε(f)",
    "Permeability μ(f)": "투자율 μ(f)",
    "Debye: Δ/(1 + jf/f₀). Lorentz: Δ·f₀²/(f₀² − f² + jfγ). A Debye μ-term models Snoek-type ferrite "
    "relaxation.": "Debye: Δ/(1 + jf/f₀). Lorentz: Δ·f₀²/(f₀² − f² + jfγ). μ의 Debye 항은 Snoek형 페라이트 "
    "완화를 나타냅니다.",
    "Fit dispersion model…": "분산 모델 피팅…",
    "Linear interpolation inside the measured range; evaluating outside it is an error. Fit a causal model "
    "to extrapolate.": "측정 범위 안에서는 선형 보간합니다. 범위 밖은 오류로 처리하므로, 범위 밖까지 쓰려면 "
    "인과적 분산 모델로 피팅하세요.",
    "Effective-medium mixture": "실효 매질 혼합", "Matrix (host)": "기지 재료 (매트릭스)",
    "Inclusion (filler)": "충전 재료 (필러)", "Volume fraction": "체적 분율", "Mixing rule": "혼합 규칙",
    "Density (computed)": "밀도 (계산값)",
    "Maxwell-Garnett: dilute spherical inclusions. Bruggeman: symmetric, valid through percolation — "
    "preferred for conductive fillers.": "Maxwell-Garnett: 묽은 구형 충전재. Bruggeman: 대칭형이며 퍼콜레이션 "
    "영역까지 유효해 전도성 필러에 적합합니다.",
    "{n} points, {lo}–{hi} GHz · source: {src}": "{n}개 점, {lo}–{hi} GHz · 출처: {src}",
    "Name in use": "이미 사용 중인 이름", "A material named “{n}” already exists.": "“{n}” 이름의 재료가 이미 있습니다.",
    "Edit material {n}": "재료 편집: {n}", "New dielectric": "새 유전체", "New dispersive material": "새 분산 재료",
    "New mixture": "새 혼합 재료", "Mixture": "혼합 재료",
    "A mixture needs at least two other materials.": "혼합 재료를 만들려면 다른 재료가 두 개 이상 필요합니다.",
    "Add material": "재료 추가", "Import measured data": "측정 데이터 가져오기",
    "CSV files (*.csv *.txt *.dat);;All files (*)": "CSV 파일 (*.csv *.txt *.dat);;모든 파일 (*)",
    "Import failed": "가져오기 실패", "Import material": "재료 가져오기", "Duplicate material": "재료 복제",
    "Material in use": "사용 중인 재료",
    "“{n}” is used by: {u}. Change those first.": "“{n}”을(를) 사용하는 곳: {u}. 먼저 변경하세요.",
    "Delete material": "재료 삭제", "Cannot delete": "삭제할 수 없습니다",
    "Add fitted material": "피팅 재료 추가", "Import library": "라이브러리 가져오기",
    "Material library (*.json);;All files (*)": "재료 라이브러리 (*.json);;모든 파일 (*)",
    "Import which material? ({n} available)": "가져올 재료를 고르세요 ({n}개 있음)",
    "All materials": "모든 재료", "Import materials": "재료 가져오기", "Export library": "라이브러리 내보내기",
    "Material library (*.json)": "재료 라이브러리 (*.json)",

    # ---- fit dialog ------------------------------------------------------------
    "Fit dispersion model — {n}": "분산 모델 피팅 — {n}", "{n} (fit)": "{n} (피팅)",
    "New material name": "새 재료 이름", "Constant loss term": "상수 손실 항", "Debye terms": "Debye 항 수",
    "Lorentz terms": "Lorentz 항 수", "Conductivity σ": "전도도 σ", "Fit": "피팅",
    "Choose the number of terms and press Fit.": "항의 개수를 고른 뒤 ‘피팅’을 누르세요.",
    "Create material": "재료 만들기", "Fit failed: {e}": "피팅 실패: {e}",
    "RMS error: ε {e:.3%}, μ {m:.3%} (relative to max |value|)": "RMS 오차: ε {e:.3%}, μ {m:.3%} (최대 |값| 대비)",
    "data": "측정", "fit": "피팅",

    # ---- preferences -----------------------------------------------------------
    "Preferences": "환경 설정", "System default": "시스템 기본값", "Light": "밝게", "Dark": "어둡게",
    "Negative dB: 20·log₁₀|Γ| (lower is better)": "음수 dB: 20·log₁₀|Γ| (낮을수록 우수)",
    "Positive dB: −20·log₁₀|Γ| (higher is better)": "양수 dB: −20·log₁₀|Γ| (높을수록 우수)",
    "Language": "언어", "A language change takes effect after restarting the application.":
        "언어 변경은 프로그램을 다시 시작한 뒤 적용됩니다.",
    "Theme": "테마", "Reflection loss sign": "반사손실 부호",
    "Internally and in project files RL is always 20·log₁₀|Γ|; this only changes how values are displayed.":
        "내부 계산과 프로젝트 파일의 RL은 항상 20·log₁₀|Γ|입니다. 이 설정은 화면 표시만 바꿉니다.",
})

KO.update({
    "In use: {u}": "사용처: {u}",
    "Bold: material is used in the current design.": "굵은 글씨: 현재 설계에서 사용 중인 재료입니다.",
})
