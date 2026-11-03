"""RAIN LINKS: rainfall from commercial microwave links (CML) of mobile operators.

Rain attenuates microwave signals between towers. From the operator's received/transmitted
signal level logs we compute path-integrated rain rate:

    A_rain = (TSL - RSL) - baseline - A_wet          [dB]
    gamma  = A_rain / L                               [dB/km]
    R      = (gamma / k) ** (1 / alpha)               [mm/h]   (ITU-R P.838 power law)

Baseline = dry-weather attenuation, taken as a rolling median over the previous hours.
Wet/dry classification uses the rolling standard deviation of attenuation (Schleiss &
Berne style), and A_wet compensates for water film on the antenna radomes.

NOTE: K_ALPHA below are APPROXIMATE values for horizontal/vertical polarisation and
must be checked against the ITU-R P.838-3 tables before the pilot uses real data.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# freq_GHz: {pol: (k, alpha)}  -- approximate, verify with ITU-R P.838-3
K_ALPHA = {
    15: {"H": (0.0448, 1.123), "V": (0.0501, 1.073)},
    18: {"H": (0.0708, 1.082), "V": (0.0691, 1.065)},
    23: {"H": (0.1286, 1.021), "V": (0.1284, 0.996)},
    38: {"H": (0.4001, 0.882), "V": (0.3884, 0.865)},
}


def k_alpha(freq_ghz: float, pol: str = "V") -> tuple[float, float]:
    """Interpolate (log-log for k, linear for alpha) between table frequencies."""
    fs = sorted(K_ALPHA)
    f = min(max(freq_ghz, fs[0]), fs[-1])
    for a, b in zip(fs, fs[1:]):
        if a <= f <= b:
            ka, aa = K_ALPHA[a][pol]
            kb, ab = K_ALPHA[b][pol]
            w = (np.log(f) - np.log(a)) / (np.log(b) - np.log(a)) if b != a else 0
            return float(np.exp(np.log(ka) + w * (np.log(kb) - np.log(ka)))), float(aa + w * (ab - aa))
    return K_ALPHA[f][pol]


@dataclass
class Link:
    id: str
    freq_ghz: float
    length_km: float
    pol: str = "V"
    lat_a: float = 0.0
    lon_a: float = 0.0
    lat_b: float = 0.0
    lon_b: float = 0.0


def rain_rate(tsl_dbm: np.ndarray, rsl_dbm: np.ndarray, link: Link, dt_min: float = 1.0,
              baseline_hours: float = 6.0, wet_std_db: float = 0.8, wet_window_min: int = 30,
              a_wet_db: float = 1.5) -> dict:
    """Return rain rate series (mm/h) and a wet/dry mask for one link."""
    att = np.asarray(tsl_dbm, float) - np.asarray(rsl_dbm, float)
    n = len(att)
    w = max(3, int(wet_window_min / dt_min))
    roll_std = np.array([att[max(0, i - w + 1): i + 1].std() for i in range(n)])
    wet = roll_std > wet_std_db
    # baseline: median of dry samples over the previous baseline_hours
    b = max(5, int(baseline_hours * 60 / dt_min))
    baseline = np.empty(n)
    for i in range(n):
        lo = max(0, i - b)
        seg = att[lo: i + 1][~wet[lo: i + 1]]
        baseline[i] = np.median(seg) if seg.size else (baseline[i - 1] if i else att[0])
    a_rain = np.where(wet, np.clip(att - baseline - a_wet_db, 0, None), 0.0)
    k, alpha = k_alpha(link.freq_ghz, link.pol)
    gamma = a_rain / link.length_km
    rate = np.where(gamma > 0, (gamma / k) ** (1 / alpha), 0.0)
    return {"rain_mm_h": rate, "wet": wet, "baseline_db": baseline, "k": k, "alpha": alpha}


def synthetic_link(link: Link, minutes=600, storm=(300, 380), peak_mm_h=40.0, seed=0):
    """TSL/RSL series with a storm, for tests and the simulator."""
    rng = np.random.default_rng(seed)
    t = np.arange(minutes)
    true = np.zeros(minutes)
    s0, s1 = storm
    mid, half = (s0 + s1) / 2, (s1 - s0) / 2
    m = (t >= s0) & (t <= s1)
    true[m] = peak_mm_h * np.cos((t[m] - mid) / half * np.pi / 2) ** 2
    k, alpha = k_alpha(link.freq_ghz, link.pol)
    att_rain = k * true ** alpha * link.length_km + np.where(true > 0, 1.5, 0)
    tsl = np.full(minutes, 18.0)
    rsl = tsl - 60 - att_rain + rng.normal(0, 0.15, minutes)
    return tsl, np.round(rsl, 1), true
