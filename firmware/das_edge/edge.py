#!/usr/bin/env python3
"""FIBER EAR edge: runs next to the DAS interrogator, turns raw strain-rate data into
band energies per channel per window and sends them to the ARLAN API.

Interrogator vendors use different file formats (HDF5, TDMS, SEG-Y, binary). Implement
`read_chunk()` for the device you get; everything after it is vendor-neutral.

    python3 edge.py --api http://SERVER:8000 --key KEY --fs 1000 --window 60 --npy-dir ./chunks
    python3 edge.py --api ... --simulate        # synthetic data, no interrogator
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))
from arlan_core.das import band_energy  # noqa: E402


def read_chunk(npy_dir: Path, seen: set) -> np.ndarray | None:
    """Default reader: .npy files with strain_rate[samples, channels], one file per window.
    Replace with the vendor SDK / file reader of the actual interrogator."""
    for f in sorted(npy_dir.glob("*.npy")):
        if f.name not in seen:
            seen.add(f.name)
            return np.load(f)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", required=True)
    ap.add_argument("--key", default="CHANGE-ME")
    ap.add_argument("--fs", type=float, default=1000.0, help="sampling rate, Hz")
    ap.add_argument("--channels", type=int, default=1200)
    ap.add_argument("--window", type=float, default=60.0, help="seconds per window")
    ap.add_argument("--npy-dir", default="chunks")
    ap.add_argument("--simulate", action="store_true")
    a = ap.parse_args()
    import requests

    seen: set = set()
    rng = np.random.default_rng()
    while True:
        if a.simulate:
            x = rng.normal(0, 1, (int(a.fs * 10), a.channels))  # 10 s of noise per window
        else:
            x = read_chunk(Path(a.npy_dir), seen)
            if x is None:
                time.sleep(5)
                continue
        e = band_energy(x, a.fs)
        r = requests.post(a.api.rstrip("/") + "/api/v1/ingest/das", json={"energies": e.tolist()},
                          headers={"X-API-Key": a.key}, timeout=30)
        print(time.strftime("%H:%M:%S"), r.status_code, r.json().get("das_ready"))
        if a.simulate:
            time.sleep(a.window)


if __name__ == "__main__":
    main()
