"""Dam-segment risk score: combines freeboard, DAS anomalies, rate of rise and in-dam sensors.

The score is a logistic combination of explainable factors, so a duty officer can see
WHY a segment is red. Weights are starting values to be tuned with hydrologists and the
2024 breach locations (Kozhevenny, Rechport bypass embankment, Podgora/Ushcheva street).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

LEVELS = [(0.25, "low"), (0.5, "medium"), (0.75, "high"), (1.01, "critical")]
LEVEL_RU = {"low": "низкий", "medium": "средний", "high": "высокий", "critical": "критический"}


@dataclass
class SegmentInput:
    id: str
    crest_m: float               # crest elevation
    level_now_m: float
    level_p90_max_m: float       # max of P90 forecast over the horizon
    rise_m_per_day: float
    das_score: float = 0.0       # 0..1 from das.DASDetector
    piezo_ratio: float | None = None  # phreatic level / dam height from in-dam sensors, 0..1
    age_years: float | None = None


def score(s: SegmentInput) -> dict:
    freeboard_now = s.crest_m - s.level_now_m
    freeboard_fc = s.crest_m - s.level_p90_max_m
    factors = {
        # less than 0.5 m of freeboard in the P90 forecast is dangerous for earthen dams
        "freeboard": max(0.0, (0.8 - freeboard_fc) / 0.8),
        "rise": min(1.0, max(0.0, s.rise_m_per_day) / 0.5),
        "das": s.das_score,
        "piezo": s.piezo_ratio if s.piezo_ratio is not None else 0.0,
        "age": min(1.0, (s.age_years or 0) / 70.0),
    }
    w = {"freeboard": 3.2, "rise": 1.2, "das": 2.8, "piezo": 1.8, "age": 0.6}
    z = -3.0 + sum(w[k] * v for k, v in factors.items())
    p = 1 / (1 + math.exp(-z))
    level = next(name for thr, name in LEVELS if p < thr)
    top = sorted(factors.items(), key=lambda kv: w[kv[0]] * kv[1], reverse=True)
    return {
        "segment_id": s.id,
        "risk": round(p, 3),
        "level": level,
        "level_ru": LEVEL_RU[level],
        "freeboard_now_m": round(freeboard_now, 2),
        "freeboard_forecast_m": round(freeboard_fc, 2),
        "factors": {k: round(v, 2) for k, v in factors.items()},
        "main_driver": top[0][0],
    }
