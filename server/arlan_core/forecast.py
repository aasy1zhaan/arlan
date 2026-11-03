"""Esil water-level forecast at Petropavlovsk, 1-15 days ahead.

Two layers:

1. `SnowmeltBaseline` - a transparent physics baseline that works from day one with
   no training data: degree-day snowmelt over the catchment -> linear reservoir ->
   level rise via a stage factor. Its inputs are snow water equivalent (from SKY
   MIRROR snow stations + satellite), the air-temperature forecast and the planned
   release from the Sergeevskoye reservoir. Parameters must be calibrated on the
   2017 / 2024 / 2025 / 2026 seasons with Kazhydromet gauge data.

2. `QuantileForecaster` - gradient boosting that learns the error of the baseline and
   of external forecasts (Tasqyn, Google Flood Hub, GloFAS) from history and returns
   P10 / P50 / P90 for each lead day. Used once enough history is loaded.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class SnowmeltBaseline:
    ddf_mm_per_c_day: float = 4.0      # degree-day factor
    t_melt_c: float = 0.0
    frozen_soil_runoff: float = 0.8    # share of melt that runs off over frozen ground
    reservoir_k_days: float = 6.0      # catchment lag
    stage_m_per_mm: float = 0.035      # level rise per mm of runoff-equivalent (calibrate!)
    release_m_per_m3s: float = 0.002   # level rise per m3/s of extra reservoir release
    recession_per_day: float = 0.03    # level decay towards base when no input

    def run(self, level_now_m: float, base_level_m: float, swe_mm: float,
            temp_forecast_c: list[float], release_extra_m3s: list[float] | None = None,
            storage_mm: float = 0.0) -> dict:
        days = len(temp_forecast_c)
        release_extra_m3s = release_extra_m3s or [0.0] * days
        swe, store, lvl = swe_mm, storage_mm, level_now_m
        out_lvl, out_melt = [], []
        for d in range(days):
            melt = min(swe, max(0.0, temp_forecast_c[d] - self.t_melt_c) * self.ddf_mm_per_c_day)
            swe -= melt
            store += melt * self.frozen_soil_runoff
            q = store / self.reservoir_k_days       # mm/day leaving the catchment store
            store -= q
            lvl = (lvl - (lvl - base_level_m) * self.recession_per_day
                   + q * self.stage_m_per_mm + release_extra_m3s[d] * self.release_m_per_m3s)
            out_lvl.append(lvl)
            out_melt.append(melt)
        lvl_arr = np.array(out_lvl)
        # uncertainty grows with lead time (+-4 cm on day 1 to ~+-40 cm on day 15, placeholder
        # until calibrated on observed errors)
        spread = 0.04 + 0.025 * np.arange(days)
        return {"p50": lvl_arr.round(3).tolist(),
                "p10": (lvl_arr - spread).round(3).tolist(),
                "p90": (lvl_arr + spread).round(3).tolist(),
                "melt_mm": np.round(out_melt, 2).tolist(),
                "swe_left_mm": round(swe, 1)}


class QuantileForecaster:
    """P10/P50/P90 per lead day from tabular features (baseline, external forecasts, sensors)."""

    def __init__(self, horizons=range(1, 16), quantiles=(0.1, 0.5, 0.9)):
        self.horizons = list(horizons)
        self.quantiles = quantiles
        self.models: dict[tuple[int, float], object] = {}

    def fit(self, X: np.ndarray, Y: np.ndarray) -> "QuantileForecaster":
        """X[n, features]; Y[n, len(horizons)] observed level h days later."""
        from sklearn.ensemble import GradientBoostingRegressor
        for j, h in enumerate(self.horizons):
            ok = ~np.isnan(Y[:, j])
            for q in self.quantiles:
                m = GradientBoostingRegressor(loss="quantile", alpha=q, n_estimators=200,
                                              max_depth=3, learning_rate=0.05)
                m.fit(X[ok], Y[ok, j])
                self.models[(h, q)] = m
        return self

    def predict(self, x: np.ndarray) -> dict:
        x = np.atleast_2d(x)
        out = {}
        for q in self.quantiles:
            key = f"p{int(q * 100)}"
            out[key] = [float(self.models[(h, q)].predict(x)[0]) for h in self.horizons]
        # enforce ordering p10 <= p50 <= p90
        p = np.sort(np.array([out["p10"], out["p50"], out["p90"]]), axis=0)
        return {"p10": p[0].round(3).tolist(), "p50": p[1].round(3).tolist(),
                "p90": p[2].round(3).tolist()}
