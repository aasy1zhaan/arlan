#!/usr/bin/env python3
"""Spring-flood scenario simulator: feeds the ARLAN API with synthetic data from all modules.

    python3 scripts/simulate.py                       # in-process, prints the state
    python3 scripts/simulate.py --url http://localhost:8000 --key CHANGE-ME
    python3 scripts/simulate.py --dump state.json     # save the resulting state (for the demo page)

The scenario is SYNTHETIC: rising Esil level over 72 h, melting snow, a seepage-like DAS
anomaly on the Podgora dam, a spring rain cell over Podgora seen by a microwave link.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "firmware" / "gnss_station"))

from arlan_core import cml, das  # noqa: E402
import gnssir  # noqa: E402


class Client:
    def __init__(self, url: str | None, key: str):
        self.h = {"X-API-Key": key}
        if url:
            import httpx
            self.c = httpx.Client(base_url=url, timeout=30)
        else:
            from fastapi.testclient import TestClient
            import app as appmod
            self.c = TestClient(appmod.app)

    def post(self, path, payload):
        r = self.c.post(path, json=payload, headers=self.h)
        r.raise_for_status()
        return r.json()

    def get(self, path):
        tok = self.c.post("/api/v1/auth/demo/admin@demo.arlan.kz").json().get("token", "")
        r = self.c.get(path, headers={"Authorization": "Bearer " + tok})
        r.raise_for_status()
        return r.json()


def run(url=None, key="CHANGE-ME", seed=7):
    rng = np.random.default_rng(seed)
    cfg = json.loads((ROOT / "config" / "city.json").read_text())
    c = Client(url, key)
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    hours = 72

    # --- water level (two river stations) and snow (two field stations), hourly
    for h in range(hours, -1, -1):
        t = now - timedelta(hours=h)
        k = (hours - h) / hours
        level = 3.0 + 2.4 * k ** 1.6 + rng.normal(0, 0.015)
        for sid, off in (("PTR-ESIL-01", 0.0), ("PTR-ESIL-02", 0.04)):
            c.post("/api/v1/ingest/gnss", {"station_id": sid, "ts": t.isoformat(), "mode": "water",
                                           "ok": True, "water_level_m": round(level + off, 3),
                                           "reflector_height_m": round(8.0 - level - off, 3),
                                           "n_arcs": int(rng.integers(6, 14)), "quality": 0.8})
        for sid, d0 in (("PTR-SNOW-01", 0.62), ("PTR-SNOW-02", 0.55)):
            depth = max(0.0, d0 * (1 - 0.45 * k) + rng.normal(0, 0.01))
            c.post("/api/v1/ingest/gnss", {"station_id": sid, "ts": t.isoformat(), "mode": "snow",
                                           "ok": True, "snow_depth_m": round(depth, 3),
                                           "n_arcs": 9, "quality": 0.75})

    # one station result produced by the REAL GNSS-IR pipeline from synthetic SNR arcs
    obs = []
    true_rh = 8.0 - (3.0 + 2.4)
    for i, (sysn, prn) in enumerate([("GPS", 5), ("GPS", 12), ("GLONASS", 3), ("GALILEO", 7), ("BEIDOU", 9)]):
        obs += gnssir.simulate_arc(true_rh, sysn, prn, t0=i * 4000, rising=i % 2 == 0, azim=170, rng=rng)
    est = gnssir.estimate(obs)

    # --- weather: warm spell ahead, extra release from the reservoir in days 3-6
    temps = [2, 4, 7, 9, 8, 6, 5, 7, 9, 10, 8, 6, 5, 4, 4]
    release = [0, 0, 40, 60, 60, 40, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    c.post("/api/v1/ingest/weather", {"ts": now.isoformat(), "temp_forecast_c": temps,
                                      "reservoir_extra_release_m3s": release})
    c.post("/api/v1/ingest/external_forecast", {"source": "tasqyn", "ts": now.isoformat(),
                                                "p50": [round(5.4 + 0.12 * d - 0.006 * d * d, 2) for d in range(15)]})

    # --- DAS: 24 calm windows (baseline), then seepage-like source on the Podgora dam
    n_ch = max(s["das"][1] for s in cfg["segments"]) + 1
    calm = das.synthetic_features(n_t=24, n_ch=n_ch, seed=1)
    for w in calm:
        c.post("/api/v1/ingest/das", {"energies": w.tolist()})
    leak = das.synthetic_features(n_t=8, n_ch=n_ch, seed=2, leak_at=(800, 818), leak_from_t=0, leak_gain=25)
    das_res = None
    for w in leak:
        das_res = c.post("/api/v1/ingest/das", {"energies": w.tolist()})

    # --- dam sensor on the bypass embankment
    c.post("/api/v1/ingest/dam_sensor", {"segment_id": "RECH", "ts": now.isoformat(), "phreatic_ratio": 0.45})

    # --- CML: 10 h of 1-minute samples, a rain cell over Podgora in the last 2 hours
    for l in cfg["cml_links"]:
        link = cml.Link(l["id"], l["freq_ghz"], l["length_km"], l.get("pol", "V"))
        storm = (480, 560) if l["id"] == "KC-0102" else (500, 520)
        peak = 32.0 if l["id"] == "KC-0102" else 3.0
        tsl, rsl, _ = cml.synthetic_link(link, minutes=600, storm=storm, peak_mm_h=peak, seed=hash(l["id"]) % 1000)
        t0 = now - timedelta(minutes=600)
        samples = [{"ts": (t0 + timedelta(minutes=i)).isoformat(), "tsl_dbm": float(tsl[i]), "rsl_dbm": float(rsl[i])}
                   for i in range(600)]
        for i in range(0, 600, 200):
            c.post("/api/v1/ingest/cml", {"link_id": l["id"], "samples": samples[i:i + 200]})

    state = c.get("/api/v1/state")
    state["_demo"] = {"synthetic": True, "gnssir_check": {"true_rh_m": true_rh,
                      "estimated_rh_m": est.get("reflector_height_m"), "n_arcs": est.get("n_arcs")},
                      "das_last": das_res}
    return state


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url")
    ap.add_argument("--key", default="CHANGE-ME")
    ap.add_argument("--dump")
    a = ap.parse_args()
    st = run(a.url, a.key)
    if a.dump:
        Path(a.dump).write_text(json.dumps(st, ensure_ascii=False, indent=1))
    print(st["briefing_ru"])
    print("\nalerts:", [x["title"] for x in st["alerts"]])
    print("gnss-ir check:", st["_demo"]["gnssir_check"])
