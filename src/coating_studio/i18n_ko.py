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
    "circuit Zs = R + jωL + 1/(jωC) (inductive X &gt; 0), or a parallel RLC circuit 1/Zs = 1/R + jωC + 1/(jωL). The RLC values are normal-incidence lumped values used "
    "for every angle and polarisation - valid for sub-wavelength unit cells below the grating-lobe onset. An optional angle dependence scales L and C with sin²θ.<br>"
    "<b>Units</b>: GHz, mm, degrees, S/m, g/cm³; the engine works in SI. The spectral axis (plots, sweep "
    "and band inputs, exports) can show THz, vacuum wavelength in µm or nm, or wavenumber in cm⁻¹ instead "
    "(Analysis settings); material model parameters stay in GHz. Thicknesses can be shown in µm or nm.":
        "<b>시간 규약</b>: e<sup>+jωt</sup>; ε = ε′ − jε″, μ = μ′ − jμ″ (ε″, μ″ &gt; 0 이면 손실).<br>"
        "<b>반사손실</b>: RL = 20·log₁₀|Γ| (음수 dB, −10 dB ≈ 90% 흡수). 표시 부호는 환경 설정에서 바꿀 수 "
        "있습니다.<br><b>Γ</b>는 접선 방향 전기장의 반사계수입니다.<br><b>층 순서</b>: 층 스택의 맨 위 행이 "
        "입사파를 마주합니다.<br><b>TE</b>: 전기장이 입사면에 수직, <b>TM</b>: 자기장이 입사면에 수직. "
        "평균 = 비편광 전력 평균.<br><b>저항 시트</b>: 병렬 임피던스 Zs = R + jX [Ω/sq] (자유공간 ≈ 376.7 Ω/sq) "
        "또는 직렬 RLC 회로 Zs = R + jωL + 1/(jωC) (유도성 X &gt; 0), 병렬 RLC 회로 1/Zs = 1/R + jωC + 1/(jωL). RLC 값은 수직 입사 기준의 집중 소자 "
        "값으로 모든 입사각과 편광에 그대로 쓰이며, 단위 셀이 파장보다 충분히 작고 회절 로브가 생기기 전까지 "
        "유효합니다. 선택 사항인 각도 의존을 켜면 L과 C가 sin²θ에 따라 변합니다.<br><b>단위</b>: GHz, mm, 도, S/m, g/cm³ (엔진 내부는 SI 단위). 스펙트럼 축(그래프, 스윕·대역 "
        "입력, 내보내기)은 해석 설정에서 THz, 진공 파장 µm·nm, 파수 cm⁻¹로 바꿀 수 있습니다. 재료 모델 파라미터는 "
        "GHz 그대로입니다. 두께는 µm·nm로도 표시할 수 있습니다.",

    # ---- main window -----------------------------------------------------------
    "Untitled": "제목 없음", "Layer stack": "층 스택", "Properties": "속성", "Analysis settings": "해석 설정",
    "Diagnostics": "진단", "Frequency": "주파수", "Angle": "입사각", "Map": "맵", "Smith chart": "Smith 차트",
    "Absorption": "흡수 분해", "Material data": "재료 물성", "Optimisation": "최적화", "Tolerance": "공차 분석",
    "Cannot compute: {e}": "계산할 수 없습니다: {e}",
    "Thickness {t}": "두께 {t}", "Areal mass {m} kg/m²": "면밀도 {m} kg/m²",
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
    "PEC": "PEC(금속)", "half-space": "반무한 매질", "Total {t}": "총 {t}",
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
    "ε″ and μ″ get their own errors (independent of ε′ and μ′ at ρ = 0), so the loss tangent varies too. A "
    "relative tolerance has no effect where the nominal loss is zero.":
        "ε″과 μ″에는 따로 오차를 주므로(ρ = 0이면 ε′, μ′과 독립) 손실 탄젠트(tan δ)도 함께 변합니다. 공칭 손실이 "
        "0이면 상대 공차는 효과가 없습니다.",
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
    "Capacitor on/off. Without a capacitor a series sheet is an inductive grid (R + jωL) and a parallel sheet has no capacitive branch.":
        "커패시터 켜기/끄기. 커패시터가 없으면 직렬 시트는 유도성 격자(R + jωL)가 되고, 병렬 시트는 용량성 가지가 없어집니다.",
    "Parallel RLC": "병렬 RLC", "no inductor": "인덕터 없음",
    "None": "없음", "Custom": "사용자 지정",
    "From grid dimensions": "격자 치수에서 계산", "From grid dimensions…": "격자 치수에서 계산…", "Pattern": "패턴",
    "Period D": "주기 D", "Strip width w": "스트립 폭 w", "Gap between patches w": "패치 사이 간격 w",
    "Keep the other element": "다른 소자 유지", "Apply grid dimensions": "격자 치수 적용",
    "Reset its optimisation range around the new value": "새 값 주변으로 최적화 범위 재설정",
    "Off: a mesh removes C and a patch removes L, so the sheet is the one the formula describes.":
        "끄면 메시는 C를, 패치는 L을 제거해 식이 설명하는 시트가 됩니다.",
    "Dense square lattice of ideal conductors, incidence in a principal plane, width or gap much smaller than the period. ε_eff = (ε_r + 1)/2 needs a dielectric thick compared with the period. The dimensions are not saved.":
        "이상 도체의 조밀한 정사각 격자, 주축 평면 입사, 주기보다 훨씬 작은 폭 또는 간격을 가정합니다. ε_eff = (ε_r + 1)/2는 주기에 비해 두꺼운 유전체가 필요합니다. 치수는 저장되지 않습니다.",
    "The width must be positive and smaller than the period.": "폭은 양수이고 주기보다 작아야 합니다.",
    "R stays at {r} Ω/sq; the formula is for ideal conductors.": "R은 {r} Ω/sq로 유지됩니다. 이 식은 이상 도체 기준입니다.",
    "Valid well below {limit}; caution above {caution}.": "{limit}보다 충분히 낮은 주파수에서 유효합니다. {caution} 이상에서는 주의하십시오.",
    "The sweep or a target reaches {f}, above the validity limit (checked once, now).":
        "스윕이나 목표가 {f}까지 이르러 유효 한계를 넘습니다 (지금 한 번만 확인).",
    "The sweep or a target reaches {f}, in the caution range (checked once, now).":
        "스윕이나 목표가 {f}까지 이르러 주의 구간에 듭니다 (지금 한 번만 확인).",
    "The width is more than half of the period; the formula assumes it is much smaller.":
        "폭이 주기의 절반을 넘습니다. 이 식은 훨씬 작은 폭을 가정합니다.",
    "Changes only the angle coefficients: a capacitance computed from grid dimensions is not recalculated.":
        "각도 계수만 바꿉니다. 격자 치수에서 계산한 커패시턴스는 다시 계산되지 않습니다.",
    "Compute L or C and the angle dependence from the dimensions of a metal mesh or patch array.":
        "금속 메시나 패치 배열의 치수에서 L 또는 C와 각도 의존을 계산합니다.",
    "Metal mesh": "금속 메시", "Patch array": "패치 배열", "Angle dependence": "각도 의존", "Effective ε": "유효 ε",
    "Coefficients": "계수", "angle coefficients": "각도 계수", "Change angle dependence": "각도 의존 변경",
    "These values are at normal incidence.": "이 값들은 수직 입사 기준입니다.",
    "The angle dependence has no element to act on.": "각도 의존을 적용할 소자가 없습니다.",
    "How L and C change with the angle. Metal mesh: L in TM; patch array: C in TE; both as 1 - sin²θ/(2 ε_eff). Only for dense arrays, before grating lobes appear. Custom values come from a file or design spec.":
        "입사각에 따라 L과 C가 변하는 방식입니다. 금속 메시는 TM의 L, 패치 배열은 TE의 C가 1 - sin²θ/(2 ε_eff)로 변합니다. 회절 로브가 생기기 전의 조밀 배열에만 유효합니다. Custom 값은 파일이나 설계 명세에서 옵니다.",
    "Effective permittivity around the grid: (ε_r + 1)/2 on a substrate, ε_r when embedded, 1 in free space.":
        "격자 주변의 유효 유전율: 기판 위면 (ε_r + 1)/2, 내장되면 ε_r, 자유공간이면 1입니다.",
    "Resistive, no reactive elements": "저항성 (리액턴스 소자 없음)",
    "In a parallel RLC sheet, 0 means no inductor.": "병렬 RLC 시트에서는 0이면 인덕터가 없습니다.",
    "Parallel RLC sheet: R {r} Ω/sq, L {l}, C {c}": "병렬 RLC 시트: R {r} Ω/sq, L {l}, C {c}",
    "Parallel RLC: 1/Zs = 1/R + jωC + 1/(jωL); the sheet opens at resonance, as slot and aperture patterns do.":
        "병렬 RLC: 1/Zs = 1/R + jωC + 1/(jωL). 슬롯·개구형 패턴처럼 공진에서 시트가 열립니다.",
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
    "This mixture references itself (directly or through other mixtures).": "이 혼합 재료가 자기 자신을 (직접 또는 다른 혼합 재료를 거쳐) 참조합니다.",
    "A uniaxial material cannot be a mixture constituent or a component of another uniaxial material.":
        "일축 이방성 재료는 혼합 재료의 성분이나 다른 일축 재료의 성분이 될 수 없습니다.",
    "Power law": "거듭제곱 법칙", "at 1 GHz": "1 GHz 값", "exponent": "지수",
    "New power-law material": "새 거듭제곱 법칙 재료",
    "Tolerance analysis": "공차 분석",
    "Angles evaluated": "평가 각도",
    "Single angle (settings above)": "한 각도 (위 설정)",
    "Ends of each target's angle range": "목표별 각도 범위의 양 끝",
    "Each target's angle grid": "목표별 각도 격자",
    "The two target modes run the analysis for each enabled target against its own band and goal, for each of its polarisations, at the two ends of its angle range or at every angle of its grid (the angles the optimiser checks), and report the joint yield (samples that pass everywhere).":
        "목표 기준 두 방식은 사용 중인 목표마다 그 목표의 대역과 목표값을 기준으로, 각 편광에서, 각도 범위의 양 끝 또는 각도 격자의 모든 각도(최적화기가 확인하는 각도)에서 분석하고 결합 수율(모든 곳을 통과한 표본의 비율)을 보고합니다.",
    "A single angle can overstate the yield of a target that spans several angles. The angle grid also checks the angles inside the range; angles between its points are not sampled. In both target modes the angle, polarisation, target and band above are not used.":
        "각도 범위가 있는 목표는 한 각도만 보면 수율이 부풀려질 수 있습니다. 각도 격자는 범위 안쪽 각도도 확인하지만, 격자 점 사이의 각도는 보지 않습니다. 목표 기준 두 방식에서는 위의 입사각·편광·목표·대역 설정을 쓰지 않습니다.",
    "Checking the target angles needs at least one enabled optimisation target.": "목표 각도를 평가하려면 사용 중인 최적화 목표가 하나 이상 있어야 합니다.",
    "Joint yield {y:.1f}% over {n} angle-grid points ({s})": "각도 격자 {n}점의 결합 수율 {y:.1f}% ({s})",
    "Weakest (plotted): {c}. Lowest yield per target: {rows}": "가장 취약한 곳(그래프): {c}. 목표별 최저 수율: {rows}",
    "Target {n}: fewer than 2 angle-grid points, so the two ends of its range were used.":
        "목표 {n}: 각도 격자 점이 2개 미만이라 각도 범위의 양 끝을 평가했습니다.",
    "Tolerance analysis: joint yield {y:.1f}% over {n} angle-grid points": "공차 분석: 각도 격자 {n}점의 결합 수율 {y:.1f}%",
    "Joint yield over every target's angle grid ({k} points): {y} ({s}). Lowest yield per target:":
        "모든 목표의 각도 격자({k}점) 결합 수율: {y} ({s}). 목표별 최저 수율:",
    "Target {n}": "목표 {n}",
    "Joint yield {y:.1f}% over {n} corners ({s})": "꼭짓점 {n}개의 결합 수율 {y:.1f}% ({s})",
    "Tolerance analysis: joint yield {y:.1f}% over {n} corners": "공차 분석: 꼭짓점 {n}개의 결합 수율 {y:.1f}%",
    "f in GHz. An empirical curve fit (e.g. the Michielssen 1993 absorber database), not a causal model: use it only inside the band it was fitted on.":
        "f의 단위는 GHz입니다. 경험적 곡선 맞춤(예: Michielssen 1993 흡수체 재료 데이터베이스)이며 인과적 모델이 아니므로, 맞춘 대역 안에서만 쓰십시오.",
    "Target {target}: the design's mu_s x d is {design_mm:.3g} mm but at least {required_mm:.3g} mm is needed (Rozanov bound, normal incidence).":
        "목표 {target}: 설계의 mu_s x d가 {design_mm:.3g} mm인데 최소 {required_mm:.3g} mm가 필요합니다(Rozanov 한계, 수직 입사).",
    "Target {target}: even the optimisation ranges reach only {max_mm:.3g} mm of mu_s x d; at least {required_mm:.3g} mm is needed (Rozanov bound, normal incidence).":
        "목표 {target}: 최적화 범위를 다 써도 mu_s x d가 {max_mm:.3g} mm에 그칩니다. 최소 {required_mm:.3g} mm가 필요합니다(Rozanov 한계, 수직 입사).",
    "{inclusion} was inverted with the {extracted} rule, but this mixture uses {model}; its values only mean something with the rule they came from.":
        "{inclusion}은(는) {extracted} 규칙으로 역산했는데 이 혼합 재료는 {model}을(를) 씁니다. 역산한 값은 그 규칙에서만 의미가 있습니다.",
    "Fraction {fraction_lo:.3g}-{fraction_hi:.3g} leaves {lo:.3g}-{hi:.3g}, the range around the loading {phi0:.3g} at which {inclusion} was inverted.":
        "분율 {fraction_lo:.3g}-{fraction_hi:.3g}이(가) {inclusion}을(를) 역산한 함량 {phi0:.3g} 주변의 범위 {lo:.3g}-{hi:.3g}을(를) 벗어납니다.",
    "Effective values tied to a mixing rule, not a measured material; use them only as the filler of a mixture.":
        "혼합 규칙에 묶인 유효값이며 측정한 재료가 아닙니다. 혼합 재료의 충전재로만 쓰십시오.",
    "Fraction {fraction_lo:.3g}-{fraction_hi:.3g} reaches {lo:.3g}-{hi:.3g}, where the {model} model is unreliable.":
        "분율 {fraction_lo:.3g}-{fraction_hi:.3g}이(가) {model} 모델을 믿기 어려운 구간 {lo:.3g}-{hi:.3g}에 들어갑니다.",
    "Frequencies {flo:.4g}-{fhi:.4g} GHz ({where}) lie outside the measured data {lo:.4g}-{hi:.4g} GHz.":
        "주파수 {flo:.4g}-{fhi:.4g} GHz({where})가 측정 데이터 범위 {lo:.4g}-{hi:.4g} GHz를 벗어납니다.",
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
    "Nominal design": "공칭 설계", "Target": "목표", "Yield {y:.1f}% ({s})": "수율 {y:.1f}% ({s})",
    "Monte-Carlo settings": "몬테카를로 설정", "Normal (value = 1σ)": "정규분포 (값 = 1σ)",
    "Uniform (± value)": "균일분포 (± 값)", "Samples": "표본 수", "Distribution": "분포",
    "Default tolerances (relative)": "기본 공차 (상대값)", "Permittivity ε": "유전율 ε",
    "Permeability μ": "투자율 μ", "Sheet impedance": "시트 임피던스",
    "Per-layer tolerances (%)": "층별 공차 (%)", "Blank cells use the default values. ρ is a coefficient from −1 to 1, not a percentage, and overrides the default ρ for that layer.":
        "빈 칸은 기본값을 사용합니다. ρ는 백분율이 아니라 −1에서 1 사이의 계수이며, 그 층에서 기본 ρ 대신 쓰입니다.", "Evaluation": "평가", "Custom yield band": "수율 대역 직접 지정",
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
    "Real/loss correlation ρ": "실수부·손실 상관계수 ρ",
    "Correlation coefficient between each layer's real-part error and loss error (ε′ with ε″, μ′ with μ″). 0 = independent; positive when both rise together, for example with filler content. Used only where the loss does not follow the real part.":
        "각 층의 실수부 오차와 손실 오차(ε′와 ε″, μ′와 μ″) 사이의 상관계수입니다. 0이면 서로 독립이고, 충전재 함량처럼 둘이 함께 커지는 경우에는 양수입니다. 손실이 실수부를 따르지 않는 곳에만 쓰입니다.",
    "Show the optimisation targets whose band includes the angle-sweep frequency (goal level over their angle range)":
        "각도 스윕 주파수가 대역 안에 드는 최적화 목표를 표시합니다(각도 범위에 걸친 요구 수준)",
    "Outline the enabled optimisation targets (band × angle range) with their goal; green when this polarisation meets the goal on the map grid, red when not":
        "켜진 최적화 목표를 대역 × 각도 범위의 사각형과 요구 수준으로 표시합니다. 맵 격자에서 이 편광이 요구를 만족하면 초록, 아니면 빨강입니다",
    # design report
    "Angles": "각도", "Band": "대역", "Goal": "요구값", "Margin": "마진", "Worst RL": "최악 RL",
    "Coating Studio {v} design report": "Coating Studio {v} 설계 보고서",
    "Comparison curves": "비교 곡선",
    "Joint yield over all target corners: {y} ({s})": "모든 목표 꼭짓점의 결합 수율: {y} ({s})",
    "Layer 1 faces the incident wave.": "1층이 입사파 쪽입니다.",
    "Margin = worst RL − goal (20·log₁₀|Γ|); ≤ 0 dB means the target is met. Each target is evaluated on its own band, angles and polarisations. The Rozanov bound is a normal-incidence thickness limit for a metal-backed absorber.":
        "마진 = 최악 RL − 요구값(20·log₁₀|Γ| 기준)이며, 0 dB 이하이면 목표를 만족합니다. 목표마다 자기 대역·각도·편광에서 평가합니다. Rozanov 한계는 금속 뒷판 흡수체의 수직 입사 두께 한계입니다.",
    "No enabled targets.": "켜진 목표가 없습니다.",
    "Reflection": "반사",
    "Reflection loss is 20·log₁₀|Γ| in dB (negative, lower is better).": "반사 손실은 20·log₁₀|Γ| dB입니다(음수, 낮을수록 좋음).",
    "Reflection loss is shown as positive dB (higher is better).": "반사 손실을 양수 dB로 표시합니다(높을수록 좋음).",
    "Rozanov bound": "Rozanov 한계",
    "Summary": "요약",
    "TE = TM (normal incidence)": "TE = TM (수직 입사)",
    "Tolerances: thickness {t} %, ε′ {e} %, ε″ {el}, μ′ {m} %, μ″ {ml}, sheet {sh} %, real/loss correlation ρ = {rho}; {d} distribution, seed {seed}. Per-layer overrides are not listed.":
        "공차: 두께 {t} %, ε′ {e} %, ε″ {el}, μ′ {m} %, μ″ {ml}, 시트 {sh} %, 실수부·손실 상관계수 ρ = {rho}, 분포 {d}, 시드 {seed}. 층별 개별 공차는 싣지 않았습니다.",
    "Yield {y} at {a}° {pol} ({s}), target {t} dB": "수율 {y}, {a}° {pol} ({s}), 목표 {t} dB",
    "Yield {y} ({s})": "수율 {y} ({s})",
    "{n} samples": "표본 {n}개", "stopped after {n} of {m} samples": "표본 {m}개 중 {n}개에서 중단",
    "Plots show the {k} targets with the lowest yield.": "그래프는 수율이 가장 낮은 목표 {k}개만 보여 줍니다.",
    "normal": "정규", "uniform": "균일",
    "design snapshot": "설계 스냅샷", "follows the real part": "실수부를 따름", "goal": "요구값", "hidden": "숨김",
    "infeasible": "불가능", "met": "만족", "no capacitor": "커패시터 없음", "not evaluated": "판정 안 함",
    "not met": "미달", "satisfied": "만족", "thicker needed": "더 두꺼워야 함",
    "Export &Touchstone (.s1p)…": "Touchstone 내보내기(.s1p)(&T)…",
    "Export &report (PDF / HTML)…": "보고서 내보내기(PDF / HTML)(&R)…",
    "Export Touchstone": "Touchstone 내보내기", "Export report": "보고서 내보내기",
    "HTML (*.html);;All files (*)": "HTML (*.html);;모든 파일 (*)",
    "Measured data (*.csv *.txt *.dat *.s1p);;All files (*)": "측정 데이터 (*.csv *.txt *.dat *.s1p);;모든 파일 (*)",
    "Polarisation at {a}° (a Touchstone file holds one):": "{a}°에서 내보낼 편광(Touchstone 파일에는 하나만 들어갑니다):",
    "Save a design report as PDF (A4) or HTML: targets and margins, layer stack, reflection plots, tolerance result and diagnostics":
        "설계 보고서를 PDF(A4)나 HTML로 저장합니다: 목표와 마진, 층 구성, 반사 그래프, 공차 결과, 진단",
    "Save the reflection coefficient S11 of the frequency sweep as a Touchstone file for circuit and network-analyser tools":
        "주파수 스윕의 반사 계수 S11을 회로 해석·네트워크 분석기 도구용 Touchstone 파일로 저장합니다",
    "Saved {n} frequencies ({pol}) to {p}": "주파수 {n}개({pol})를 {p}에 저장했습니다",
    "Show a measured reflection-loss curve (CSV or Touchstone .s1p) on the Frequency tab":
        "측정한 반사 손실 곡선(CSV 또는 Touchstone .s1p)을 주파수 탭에 표시합니다",
    "Touchstone (*.s1p);;All files (*)": "Touchstone (*.s1p);;모든 파일 (*)",
    # spectral axis display unit (DEVELOPMENT_HISTORY 3.21)
    "Best RL {v} dB at {x}": "최고 RL {v} dB ({x})",
    "Frequency (or wavelength) of the angle sweep, in the spectral unit of the Analysis settings.":
        "각도 스윕의 주파수(또는 파장). 해석 설정의 스펙트럼 단위를 따릅니다.",
    "Frequency [{u}]": "주파수 [{u}]", "Wavelength [{u}]": "파장 [{u}]", "Wavenumber [{u}]": "파수 [{u}]",
    "Wavelength": "파장", "Wavenumber": "파수",
    "Measured data covers {lo:.4g}-{hi:.4g} {u} but {flo:.4g}-{fhi:.4g} {u} is requested.":
        "측정 데이터는 {lo:.4g}-{hi:.4g} {u} 범위인데 {flo:.4g}-{fhi:.4g} {u}를 요청했습니다.",
    "Passivity: eps'' < 0 (gain) near {f:.4g} {u}.": "수동성: {f:.4g} {u} 부근에서 ε″ < 0 (이득).",
    "Passivity: mu'' < 0 (gain) near {f:.4g} {u}.": "수동성: {f:.4g} {u} 부근에서 μ″ < 0 (이득).",
    "Spectral range {flo:.4g}-{fhi:.4g} {u} ({where}) lies outside the measured data {lo:.4g}-{hi:.4g} {u}.":
        "스펙트럼 범위 {flo:.4g}-{fhi:.4g} {u}({where})가 측정 데이터 {lo:.4g}-{hi:.4g} {u} 밖에 있습니다.",
    "Spectral axis": "스펙트럼 축", "Sweep at": "스윕 위치",
    "Unit of the spectral axis in plots, inputs and exports. Wavelengths are vacuum wavelengths (c/f). Display only: the project keeps frequencies.":
        "그래프·입력·내보내기에 쓰는 스펙트럼 축 단위입니다. 파장은 진공 파장(c/f)입니다. 표시 전용이며 프로젝트는 주파수로 저장합니다.",
    "Zs({x}) = {z} Ω/sq": "Zs({x}) = {z} Ω/sq",
    "{n} points, {range} · source: {src}": "{n}점, {range} · 출처: {src}",
    "{x}, value = {v}": "{x}, 값 = {v}",
    "{x}, θ = {a}°, RL = {v} dB": "{x}, θ = {a}°, RL = {v} dB",
    "Γ locus over the sweep; ● {a}, ■ {b}": "스윕에 따른 Γ 궤적; ● {a}, ■ {b}",
    # thickness display unit (DEVELOPMENT_HISTORY 3.22)
    "Thickness unit": "두께 단위",
    "Unit of layer thicknesses in the layer stack, properties, optimisation and report. Display only: the project keeps metres.":
        "층 스택·속성·최적화·보고서에 쓰는 두께 단위입니다. 표시 전용이며 프로젝트는 m로 저장합니다.",
    # wavelength-spaced sweep (DEVELOPMENT_HISTORY 3.23)
    "Point spacing": "점 간격", "Even in frequency": "주파수 등간격", "Even in wavelength": "파장 등간격",
    "Logarithmic (log axis)": "로그 (로그 축)",
    "How the sweep points are spread. Even in wavelength suits optical spectra; it is sparse at high frequencies ((f_max/f_min)² wider steps), so a narrow band there may fall between points. Logarithmic also draws a log axis.":
        "스윕 점을 어떻게 나눌지 정합니다. 파장 등간격은 광학 스펙트럼에 맞습니다. 고주파 쪽 간격이 (f_max/f_min)²배 넓어서 그쪽의 좁은 대역은 "
        "점 사이에 빠질 수 있습니다. 로그는 로그 축으로도 그립니다.",
    # PDF report (DEVELOPMENT_HISTORY 3.24)
    "PDF (*.pdf)": "PDF (*.pdf)", "HTML (*.html)": "HTML (*.html)",
    # Filler inversion dialog (DEVELOPMENT_HISTORY 3.31)
    "Invert filler…": "충전재 역산…", "Invert filler": "충전재 역산",
    "Treat this measured composite as a mixture and compute the effective filler table.":
        "이 측정 복합재를 혼합물로 보고 충전재의 유효값 표를 계산합니다.",
    "This table is already an inverted filler, not a measured composite.":
        "이 표는 이미 역산된 충전재이며, 측정한 복합재가 아닙니다.",
    "{n} mixture": "{n} 혼합물", "Add inverted filler": "역산 충전재 추가",
    "Invert filler — {n}": "충전재 역산 — {n}", "{n} filler": "{n} 충전재", "Choose…": "선택…",
    "Weight fraction": "무게 분율", "Composite and filler": "복합재와 충전재",
    "Filler loading (0–1)": "충전재 함량 (0–1)", "Filler density [kg/m³]": "충전재 밀도 [kg/m³]",
    "Matrix density [kg/m³]": "매트릭스 밀도 [kg/m³]", "Enter values": "값 입력", "CSV file": "CSV 파일",
    "Project material": "프로젝트 재료", "No file chosen.": "선택한 파일이 없습니다.", "Browse…": "찾아보기…",
    "Matrix": "매트릭스", "Composite": "복합재", "Loading": "함량", "Add CSV…": "CSV 추가…",
    "Add material…": "재료 추가…", "Remove": "제거",
    "Validation: composites at other loadings (optional)": "검증: 다른 함량의 복합재 (선택 사항)",
    "Compute": "계산", "Set negative loss to 0 where allowed": "허용되는 점의 음수 손실을 0으로 설정",
    "Only for a few noisy points, and only when you accept the change: those points no longer reproduce the measurement.":
        "잡음이 있는 소수의 점에만, 변경을 받아들일 때만 쓰세요. 그 점들은 더 이상 측정값을 재현하지 않습니다.",
    "Fill in the inputs and press Compute.": "입력을 채우고 계산을 누르세요.",
    "Also create a mixture with the project matrix": "프로젝트 매트릭스로 혼합 재료도 만들기",
    "The result holds effective values tied to this mixing rule and loading, not measured properties of the filler. Confirm it on a new sample.":
        "결과는 이 혼합 규칙과 함량에 묶인 유효값이며, 충전재의 측정 물성이 아닙니다. 새 시편으로 확인하세요.",
    "The inputs changed. Press Compute again.": "입력이 바뀌었습니다. 계산을 다시 누르세요.",
    "Matrix data": "매트릭스 데이터", "Validation data": "검증 데이터", "Validation": "검증",
    "The project has no other measured material.": "프로젝트에 다른 측정 재료가 없습니다.",
    "Composite at another loading": "다른 함량의 복합재",
    "Enter ε′, ε″, μ′ and μ″ of the matrix.": "매트릭스의 ε′, ε″, μ′, μ″를 입력하세요.",
    "Choose the matrix CSV file.": "매트릭스 CSV 파일을 선택하세요.",
    "The project has no matrix material to choose: built-in demonstration values cannot be used.":
        "선택할 수 있는 매트릭스 재료가 프로젝트에 없습니다. 내장 시연값은 쓸 수 없습니다.",
    "Choose the mixing rule.": "혼합 규칙을 선택하세요.",
    "Enter a filler loading between 0 and 1.": "충전재 함량을 0과 1 사이로 입력하세요.",
    "Enter a positive filler density.": "충전재 밀도를 양수로 입력하세요.",
    "A weight fraction needs a positive matrix density.": "무게 분율에는 양수의 매트릭스 밀도가 필요합니다.",
    "enter a loading between 0 and 1": "함량을 0과 1 사이로 입력하세요",
    "Cannot evaluate the matrix on the composite's frequencies: {e}": "복합재의 주파수에서 매트릭스를 계산할 수 없습니다: {e}",
    "No usable filler table: {g} point(s) with gain, {o} beyond what this rule can represent, {b} on another root. Do not invent values: try the other rule, or measure more loadings.":
        "쓸 수 있는 충전재 표가 없습니다. 이득이 있는 점 {g}개, 이 규칙이 표현할 수 없는 점 {o}개, 다른 근으로 간 점 {b}개입니다. 값을 지어내지 말고 다른 규칙을 쓰거나 함량을 더 측정하세요.",
    "{n} gain point(s) can be set to 0 if you accept it.": "받아들이면 이득이 있는 점 {n}개를 0으로 설정할 수 있습니다.",
    "Volume fraction used: {v:.4g}": "사용한 체적 분율: {v:.4g}",
    "Error amplification κ (median / max): ε {e}, μ {m}": "오차 증폭 κ (중앙값 / 최댓값): ε {e}, μ {m}",
    "Prediction change for a 10 % loading error: ε {e:.1%}, μ {m:.1%}": "함량 오차 10 %에 따른 예측 변화: ε {e:.1%}, μ {m:.1%}",
    "Difference from the other mixing rule: ε {e:.1%}, μ {m:.1%}": "다른 혼합 규칙과의 차이: ε {e:.1%}, μ {m:.1%}",
    "The other mixing rule cannot represent this composite.": "다른 혼합 규칙은 이 복합재를 표현할 수 없습니다.",
    "Validation {n}: {e}": "검증 {n}: {e}", "Validation {n} at {p:.4g}: ε {e:.1%}, μ {m:.1%}": "검증 {n} (함량 {p:.4g}): ε {e:.1%}, μ {m:.1%}",
    "ill-conditioned": "악조건", "loss set to 0": "손실을 0으로 설정", "blocked": "차단",
    "At {n} point(s) measurement errors grow more than {k:g}-fold in the filler values: trust predictions, not the values.":
        "{n}개 점에서 측정 오차가 충전재 값에 {k:g}배 넘게 커집니다. 값이 아니라 예측을 믿으세요.",
    "{n} point(s) have Re ≤ 0.": "{n}개 점의 실수부가 0 이하입니다.",
    "Loss set to 0 at {n} point(s); the composite there is reproduced only to {w:.3g}.":
        "{n}개 점의 손실을 0으로 설정했습니다. 그 점의 복합재는 {w:.3g}까지만 재현됩니다.",
    "A 10 % loading error moves predictions by more than {p:.0%}.": "함량 오차 10 %가 예측을 {p:.0%} 넘게 바꿉니다.",
    "The other mixing rule predicts differently by more than {p:.0%}.": "다른 혼합 규칙의 예측이 {p:.0%} 넘게 다릅니다.",
    "No composite at another loading was given: predictions at other loadings are untested.":
        "다른 함량의 복합재가 없어 다른 함량의 예측은 검증되지 않았습니다.",
    "{n}: prediction error above {p:.0%}.": "{n}: 예측 오차가 {p:.0%}를 넘습니다.",
    # Odelevskiy mixing rule (DEVELOPMENT_HISTORY 3.32)
    "Odelevskiy (non-spherical)": "Odelevskiy (비구형)", "Shape factor N": "형상 인자 N",
    "Percolation threshold": "퍼콜레이션 임계값",
    "Shape factor N of the inclusions. Fit it to measurements: it often differs from the value computed from the particle size.":
        "입자의 형상 인자 N입니다. 측정값에 맞춰 구하세요. 입자 크기로 계산한 값과 다른 경우가 많습니다.",
    "Percolation threshold as a volume fraction. N = 1/3 with a threshold of 1 is Maxwell-Garnett.":
        "체적 분율로 나타낸 퍼콜레이션 임계값입니다. N = 1/3, 임계값 1이면 Maxwell-Garnett입니다.",
    "Enter a shape factor between 0 and 1 and a percolation threshold above 0 and at most 1.":
        "형상 인자는 0과 1 사이, 퍼콜레이션 임계값은 0 초과 1 이하로 입력하세요.",
    "The volume fraction must be below the percolation threshold.": "체적 분율은 퍼콜레이션 임계값보다 작아야 합니다.",
    "The volume fraction {fraction:.3g} is at or above the percolation threshold {pc:.3g}, where the Odelevskiy rule has no meaning.":
        "체적 분율 {fraction:.3g}이(가) 퍼콜레이션 임계값 {pc:.3g} 이상입니다. 이 범위에서 Odelevskiy 규칙은 의미가 없습니다.",
    "Difference without the percolation term: ε {e:.1%}, μ {m:.1%}": "퍼콜레이션 항을 뺐을 때의 차이: ε {e:.1%}, μ {m:.1%}",
    "A threshold of 1 has no percolation term to compare.": "임계값이 1이면 비교할 퍼콜레이션 항이 없습니다.",
    "The same shape factor without percolation cannot represent this composite.":
        "같은 형상 인자로 퍼콜레이션 항을 빼면 이 복합재를 표현할 수 없습니다.",
    # dispersion-term f0 and gamma in the spectral display unit
    "Vacuum wavelength of the resonance, λ₀ = c/f₀.": "공진의 진공 파장, λ₀ = c/f₀.",
    "Wavenumber of the resonance, ν̃₀ = f₀/c.": "공진의 파수, ν̃₀ = f₀/c.",
    "γ is a damping rate (a frequency interval). A wavelength has no equivalent of it, so it is shown in THz.":
        "γ는 감쇠율(주파수 간격)입니다. 파장으로 바꿀 수 없어 THz로 표시합니다.",
    "A bound of 0 Hz or below has no wavelength or wavenumber; switch the spectral axis to a frequency unit to "
    "edit it.": "0 Hz 이하의 경계는 파장이나 파수로 나타낼 수 없습니다. 편집하려면 스펙트럼 축을 주파수 단위로 바꾸십시오.",
    "Material parameter tolerances": "재료 파라미터 공차",
    "Tolerance (%)": "공차 (%)",
    "Blank cells leave the parameter at its value. A material parameter is drawn once per sample for the material, so every layer that uses it moves together; shifting a term's f₀ or a volume fraction moves the curve along the frequency axis. The layer ε and μ tolerances still apply on top, so lower them when these already cover the same error.":
        "빈 칸의 파라미터는 흔들지 않습니다. 재료 파라미터는 표본마다 재료 단위로 한 번 뽑으므로, 그 재료를 쓰는 모든 층이 함께 움직입니다. 분산 항의 f₀나 체적 분율을 흔들면 곡선이 주파수 축으로 이동합니다. 층의 ε·μ 공차는 그 위에 그대로 곱해지므로, 같은 오차를 이미 여기서 다룬다면 층 공차를 낮추세요.",
    "Change material parameter tolerance": "재료 파라미터 공차 변경",
    "Material parameters varied per sample (relative): {items}.": "표본마다 흔든 재료 파라미터(상대값): {items}.",
    "Uniaxial (in-plane / normal)": "일축 이방성 (면내 / 법선)",
    "Uniaxial material (axis along the layer normal)": "일축 이방성 재료 (축 = 층의 법선)",
    "In-plane (ε∥, μ∥)": "면내 (ε∥, μ∥)",
    "Normal (ε⊥, μ⊥)": "법선 (ε⊥, μ⊥)",
    "Each component is another material, for example two Odelevskiy mixtures of the same flakes with in-plane and normal shape factors. Normal incidence sees only the in-plane values; the normal values act at oblique incidence (μ⊥ in TE, ε⊥ in TM). The density is that of the in-plane material. A uniaxial material cannot be a mixture constituent.":
        "각 성분은 다른 재료입니다. 예를 들어 같은 플레이크를 면내·법선 형상 인자로 나눈 Odelevskiy 혼합 재료 두 개를 씁니다. 수직 입사는 면내 값만 보고, 법선 값은 사입사에서 작용합니다(TE는 μ⊥, TM은 ε⊥). 밀도는 면내 재료의 밀도입니다. 일축 재료는 혼합 재료의 성분이 될 수 없습니다.",
    "A uniaxial material needs at least one other (isotropic) material.": "일축 재료에는 다른 (등방성) 재료가 하나 이상 필요합니다.",
    "New uniaxial material": "새 일축 재료",
    "Havriliak-Negami": "Havriliak-Negami",
    "Havriliak-Negami term": "Havriliak-Negami 항",
    "Havriliak-Negami terms": "Havriliak-Negami 항",
    "Δ/(1 + (jf/f₀)^α)^β: a broadened relaxation. β = 1 is Cole-Cole, α = 1 Cole-Davidson, α = β = 1 Debye; both exponents between 0 and 1.":
        "Δ/(1 + (jf/f₀)^α)^β: 넓게 퍼진 완화입니다. β = 1이면 Cole-Cole, α = 1이면 Cole-Davidson, α = β = 1이면 Debye이고, 두 지수는 0과 1 사이입니다.",
    "Broadened relaxations Δ/(1 + (jf/f₀)^α)^β, for polymer and composite data that one Debye term does not fit.":
        "넓게 퍼진 완화 Δ/(1 + (jf/f₀)^α)^β입니다. Debye 항 하나로 맞지 않는 고분자·복합재 데이터에 씁니다.",
    "A Havriliak-Negami term needs 0 < α ≤ 1 and 0 < β ≤ 1; outside that range it can be non-causal or show gain.":
        "Havriliak-Negami 항은 0 < α ≤ 1, 0 < β ≤ 1이어야 합니다. 범위 밖에서는 인과성이 깨지거나 이득이 생길 수 있습니다.",
})
