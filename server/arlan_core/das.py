"""FIBER EAR: anomaly detection on Distributed Acoustic Sensing (DAS) data.

DAS turns a fibre into thousands of vibration sensors ("channels", one every few metres).
Raw DAS is far too big to ship (gigabytes per hour), so an edge script next to the
interrogator reduces it to band energies per channel per window (see
firmware/das_edge/edge.py). This module works on those features:

  features[t, ch, band]  -> energy (any linear unit), one row per time window

Approach (deliberately simple and explainable for the pilot):
1. Baseline per channel and band: median and MAD over a calm reference period
   (winter, frozen ground, no flood).
2. Robust z-score of the log-energy of each new window against that baseline.
3. A channel is anomalous when its z-score stays above a threshold for
   `persistence` consecutive windows (seepage and piping make sustained,
   localised low-frequency noise; traffic and footsteps are short).
4. Channels are mapped to dam segments by fibre distance; a segment's score is the
   share of anomalous channels plus the strength of the strongest one.

Thresholds are starting values; they must be tuned on the pilot's own winter baseline.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

DEFAULT_BANDS = [(0.5, 5.0), (5.0, 20.0), (20.0, 100.0)]  # Hz


def band_energy(strain_rate: np.ndarray, fs: float, bands=DEFAULT_BANDS) -> np.ndarray:
    """strain_rate[samples, channels] -> energy[channels, bands] for one window."""
    x = strain_rate - strain_rate.mean(axis=0, keepdims=True)
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))[:, None], axis=0)) ** 2
    freqs = np.fft.rfftfreq(len(x), 1 / fs)
    out = np.empty((x.shape[1], len(bands)))
    for j, (lo, hi) in enumerate(bands):
        m = (freqs >= lo) & (freqs < hi)
        out[:, j] = spec[m].sum(axis=0) if m.any() else 0.0
    return out


@dataclass
class Segment:
    id: str
    ch_from: int
    ch_to: int  # inclusive


@dataclass
class DASDetector:
    z_threshold: float = 4.0
    persistence: int = 3
    band_weights: list[float] = field(default_factory=lambda: [1.0, 0.7, 0.2])
    med: np.ndarray | None = None
    mad: np.ndarray | None = None

    def fit(self, baseline: np.ndarray) -> "DASDetector":
        """baseline[t, ch, band] from a calm period."""
        logb = np.log10(baseline + 1e-12)
        self.med = np.median(logb, axis=0)
        self.mad = np.median(np.abs(logb - self.med), axis=0) * 1.4826 + 1e-3
        return self

    def zscores(self, feats: np.ndarray) -> np.ndarray:
        """feats[t, ch, band] -> combined z[t, ch] (weighted over bands, only increases)."""
        if self.med is None:
            raise RuntimeError("fit() the detector on a baseline first")
        z = (np.log10(feats + 1e-12) - self.med) / self.mad
        w = np.array(self.band_weights[: z.shape[2]])
        return np.clip(z, 0, None) @ (w / w.sum())

    def detect(self, feats: np.ndarray) -> dict:
        z = self.zscores(feats)
        above = z > self.z_threshold
        # persistence: anomalous if the last `persistence` windows are all above
        k = min(self.persistence, len(z))
        persistent = above[-k:].all(axis=0)
        return {"z_last": z[-1], "z_max": z.max(axis=0), "anomalous": persistent}

    def segment_scores(self, feats: np.ndarray, segments: list[Segment]) -> dict[str, dict]:
        d = self.detect(feats)
        out = {}
        for s in segments:
            sl = slice(s.ch_from, s.ch_to + 1)
            an = d["anomalous"][sl]
            zl = d["z_last"][sl]
            share = float(an.mean()) if an.size else 0.0
            # strength only counts on persistent anomalies (short traffic bursts are ignored)
            peak = float(zl[an].max()) if an.any() else 0.0
            background = float(np.median(zl)) if zl.size else 0.0
            # 0..1: half from how much of the segment is anomalous, half from peak strength,
            # plus a small term for a generally noisier-than-usual segment
            score = min(1.0, 0.5 * min(1.0, share * 10)
                        + 0.5 * min(1.0, peak / (2 * self.z_threshold))
                        + min(0.15, background / (4 * self.z_threshold)))
            hot = [int(s.ch_from + i) for i in np.flatnonzero(an)]
            out[s.id] = {"score": round(score, 3), "anomalous_channels": hot,
                         "peak_z": round(peak, 2)}
        return out


def synthetic_features(n_t=48, n_ch=400, seed=0, leak_at: tuple[int, int] | None = None,
                       leak_from_t: int = 30, leak_gain: float = 30.0) -> np.ndarray:
    """Background noise with an optional sustained low-frequency 'seepage' source."""
    rng = np.random.default_rng(seed)
    base = 10 ** rng.normal(0, 0.15, (n_t, n_ch, 3))
    base *= np.array([1.0, 0.6, 0.3])
    # short traffic bursts (should NOT trigger: they don't persist)
    for _ in range(20):
        t, c = rng.integers(0, n_t), rng.integers(0, n_ch - 10)
        base[t, c:c + 10, 1:] *= 50
    if leak_at:
        a, b = leak_at
        base[leak_from_t:, a:b, 0] *= leak_gain
        base[leak_from_t:, a:b, 1] *= leak_gain / 3
    return base
