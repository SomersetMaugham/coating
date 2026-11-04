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
