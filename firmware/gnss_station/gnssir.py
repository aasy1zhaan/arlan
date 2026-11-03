"""GNSS Interferometric Reflectometry (GNSS-IR) core.

Takes SNR observations (time, satellite, elevation, azimuth, SNR in dB-Hz) and returns
the reflector height (RH): vertical distance from the antenna phase centre down to the
reflecting surface (water or snow).

Physics: the direct and the surface-reflected signal interfere. After removing the
direct-signal trend, SNR oscillates as  A*cos(4*pi*RH/lambda * sin(E) + phi).
So in the variable x = sin(E) the oscillation frequency is f = 2*RH/lambda cycles per
unit of x, and RH = f * lambda / 2. We find f with a Lomb-Scargle periodogram,
because samples are unevenly spaced in sin(E).

Pure numpy/scipy, no hardware dependencies: runs on the Pi and on the server.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import numpy as np
from scipy.signal import lombscargle

C = 299_792_458.0
# Carrier wavelengths (m). GLONASS L1 is FDMA (1598-1606 MHz); the centre value is used,
# the error this introduces in RH is well under 1%.
WAVELENGTH = {
    "GPS": C / 1575.42e6,      # L1 C/A, ~0.1903 m
    "GALILEO": C / 1575.42e6,  # E1
    "GLONASS": C / 1602.0e6,   # L1OF centre
    "BEIDOU": C / 1561.098e6,  # B1I
}

TALKER_TO_SYSTEM = {"GP": "GPS", "GA": "GALILEO", "GL": "GLONASS", "GB": "BEIDOU", "BD": "BEIDOU"}


@dataclass
class Obs:
    t: float          # unix seconds, UTC
    system: str       # GPS / GLONASS / GALILEO / BEIDOU
    prn: int
    elev: float       # degrees
    azim: float       # degrees
    snr: float        # dB-Hz


@dataclass
class ArcResult:
    system: str
    prn: int
    t_mid: float
    azim_mean: float
    rh: float          # metres
    amplitude: float
    peak2noise: float
    n: int
    elev_span: float
    ok: bool


@dataclass
class Settings:
    elev_min: float = 5.0
    elev_max: float = 25.0
    rh_min: float = 0.5
    rh_max: float = 8.0
    rh_step: float = 0.002
    min_points: int = 30
    min_elev_span: float = 8.0
    min_peak2noise: float = 3.0
    max_gap_s: float = 300.0
    # list of [from_deg, to_deg] sectors that look at the target surface; empty = all
    azimuth_mask: list[list[float]] = field(default_factory=list)
    poly_order: int = 2


def in_azimuth_mask(az: float, mask: list[list[float]]) -> bool:
    if not mask:
        return True
    for a, b in mask:
        if a <= b and a <= az <= b:
            return True
        if a > b and (az >= a or az <= b):  # sector that wraps through north
            return True
    return False


def split_arcs(obs: list[Obs], s: Settings) -> list[list[Obs]]:
    """Split one satellite's track into rising/setting arcs inside the elevation window."""
    obs = sorted(obs, key=lambda o: o.t)
    arcs: list[list[Obs]] = []
    cur: list[Obs] = []
    direction = 0
    for o in obs:
        inside = s.elev_min <= o.elev <= s.elev_max and in_azimuth_mask(o.azim, s.azimuth_mask)
        if not inside or o.snr <= 0:
            if cur:
                arcs.append(cur)
            cur, direction = [], 0
            continue
        if cur:
            gap = o.t - cur[-1].t
            d = np.sign(o.elev - cur[-1].elev)
            if gap > s.max_gap_s or (direction and d and d != direction):
                arcs.append(cur)
                cur, direction = [], 0
            elif d:
                direction = int(d)
        cur.append(o)
    if cur:
        arcs.append(cur)
    return arcs


def solve_arc(arc: list[Obs], s: Settings) -> ArcResult | None:
    if len(arc) < s.min_points:
        return None
    sysname = arc[0].system
    lam = WAVELENGTH.get(sysname)
    if lam is None:
        return None
    elev = np.array([o.elev for o in arc])
    span = float(elev.max() - elev.min())
    if span < s.min_elev_span:
        return None
    x = np.sin(np.radians(elev))
    snr_lin = 10 ** (np.array([o.snr for o in arc]) / 20.0)  # dB-Hz -> linear amplitude
    # remove the direct-signal trend
    coef = np.polyfit(x, snr_lin, s.poly_order)
    y = snr_lin - np.polyval(coef, x)
    y = y - y.mean()
    if np.allclose(y, 0):
        return None

    rh_grid = np.arange(s.rh_min, s.rh_max, s.rh_step)
    freq = 2.0 * rh_grid / lam               # cycles per unit sin(E)
    pgram = lombscargle(x, y, 2 * np.pi * freq)
    amp = np.sqrt(4 * pgram / len(x))
    i = int(np.argmax(amp))
    peak = float(amp[i])
    # noise: mean amplitude away from the peak (outside +-0.3 m)
    far = np.abs(rh_grid - rh_grid[i]) > 0.3
    noise = float(amp[far].mean()) if far.any() else float(amp.mean())
    p2n = peak / noise if noise > 0 else 0.0
    edge = i == 0 or i == len(rh_grid) - 1
    ok = (p2n >= s.min_peak2noise) and not edge
    return ArcResult(
        system=sysname,
        prn=arc[0].prn,
        t_mid=float(np.mean([o.t for o in arc])),
        azim_mean=float(np.mean([o.azim for o in arc])),
        rh=float(rh_grid[i]),
        amplitude=peak,
        peak2noise=p2n,
        n=len(arc),
        elev_span=span,
        ok=ok,
    )


def estimate(obs: Iterable[Obs], s: Settings | None = None) -> dict:
    """Run GNSS-IR on a window of observations and return a robust reflector height."""
    s = s or Settings()
    by_sat: dict[tuple[str, int], list[Obs]] = {}
    for o in obs:
        by_sat.setdefault((o.system, o.prn), []).append(o)

    results: list[ArcResult] = []
    for track in by_sat.values():
        for arc in split_arcs(track, s):
            r = solve_arc(arc, s)
            if r is not None:
                results.append(r)

    good = [r for r in results if r.ok]
    if not good:
        return {"ok": False, "n_arcs": 0, "n_candidates": len(results), "arcs": []}

    rh = np.array([r.rh for r in good])
    # robust: drop arcs further than 3 MAD from the median
    med = float(np.median(rh))
    mad = float(np.median(np.abs(rh - med))) or 0.01
    keep = np.abs(rh - med) <= 3 * 1.4826 * mad
    rh_k = rh[keep]
    w = np.array([r.peak2noise for r in good])[keep]
    rh_est = float(np.average(rh_k, weights=w))
    std = float(np.std(rh_k)) if len(rh_k) > 1 else 0.0
    quality = float(min(1.0, len(rh_k) / 10.0) * (1.0 / (1.0 + std / 0.05)))
    return {
        "ok": True,
        "reflector_height_m": round(rh_est, 4),
        "rh_std_m": round(std, 4),
        "n_arcs": int(keep.sum()),
        "n_candidates": len(results),
        "quality": round(quality, 3),
        "t_mid": float(np.mean([r.t_mid for r in good])),
        "arcs": [r.__dict__ for r in good],
    }


def to_level(rh: float, antenna_elevation_m: float) -> float:
    """Water surface elevation = antenna elevation (in a height datum) - reflector height."""
    return antenna_elevation_m - rh


def to_snow_depth(rh: float, bare_ground_rh: float) -> float:
    """Snow depth = reflector height over bare ground - reflector height over snow."""
    return max(0.0, bare_ground_rh - rh)


def simulate_arc(rh: float, system: str = "GPS", prn: int = 1, t0: float = 0.0,
                 rising: bool = True, azim: float = 180.0, noise_db: float = 0.5,
                 elev_range=(4.0, 26.0), seconds: int = 1800, quantize: bool = True,
                 rng: np.random.Generator | None = None) -> list[Obs]:
    """Synthetic SNR arc for tests and the simulator (NMEA-like integer SNR)."""
    rng = rng or np.random.default_rng(0)
    lam = WAVELENGTH[system]
    t = np.arange(seconds, dtype=float)
    e0, e1 = elev_range
    elev = np.linspace(e0, e1, seconds) if rising else np.linspace(e1, e0, seconds)
    x = np.sin(np.radians(elev))
    direct = 10 ** ((35 + 12 * x) / 20)              # trend: SNR grows with elevation
    mult = 0.25 * direct * np.cos(4 * np.pi * rh / lam * x + 0.7)
    snr = 20 * np.log10(np.abs(direct + mult)) + rng.normal(0, noise_db, seconds)
    if quantize:
        snr = np.round(snr)
    return [Obs(t0 + ti, system, prn, float(e), azim, float(sv)) for ti, e, sv in zip(t, elev, snr)]
