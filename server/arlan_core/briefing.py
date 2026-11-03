"""Daily briefing for the emergency service, generated from the platform state.

Template-based on purpose: the numbers in it come straight from the state, nothing is
invented. The Kazakh template must be reviewed by a native speaker before the pilot.
"""
from __future__ import annotations

from .alerts import FACTOR_RU

ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def briefing_text(st: dict, lang: str = "ru") -> str:
    lv = st["level"]
    fc = st["forecast"]
    peak = max(fc["p50"]) if fc["p50"] else lv["now_m"]
    peak_day = fc["p50"].index(peak) + 1 if fc["p50"] else 0
    segs = sorted(st["segments"], key=lambda s: ORDER[s["level"]])
    worst = segs[0] if segs else None
    rain_max = max((r["rain_max_3h_mm_h"] for r in st.get("rain", {}).values()), default=0.0)
    if lang == "kk":
        lines = [
            f"Есіл өзенінің деңгейі: {lv['now_m']:.2f} м (тәулігіне {lv['rise_m_per_day']:+.2f} м).",
            f"Болжам: {peak_day}-күні шамамен {peak:.2f} м (P90: {max(fc['p90']):.2f} м).",
        ]
        if worst:
            lines.append(f"Ең қауіпті учаске: {worst['name']} — тәуекел {worst['risk']:.0%}.")
        lines.append(f"Қардағы су қоры: {st['snow']['swe_mm']:.0f} мм. Жаңбыр (3 сағ макс.): {rain_max:.1f} мм/сағ.")
        return "\n".join(lines)
    lines = [
        f"Уровень Есиля: {lv['now_m']:.2f} м ({lv['rise_m_per_day']:+.2f} м за сутки), опасная отметка {lv['danger_m']:.2f} м.",
        f"Прогноз: пик около {peak:.2f} м на {peak_day}-й день (P90 до {max(fc['p90']):.2f} м).",
    ]
    if worst:
        lines.append(f"Самый опасный участок: {worst['name']} — риск {worst['risk']:.0%} ({worst['level_ru']}), "
                     f"причина: {FACTOR_RU.get(worst['main_driver'], worst['main_driver'])}.")
    hot = [s for s in segs if s["level"] in ("high", "critical")]
    if hot:
        lines.append("Рекомендация: усилить патрулирование и подготовить технику на участках: "
                     + ", ".join(s["name"] for s in hot) + ".")
    lines.append(f"Запас воды в снеге: {st['snow']['swe_mm']:.0f} мм. Ливень (макс. за 3 ч): {rain_max:.1f} мм/ч.")
    return "\n".join(lines)
