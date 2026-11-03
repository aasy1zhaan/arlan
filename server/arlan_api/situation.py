"""City situation: sensors -> forecast -> dam risk -> alerts. Uses arlan_core models."""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import numpy as np

from arlan_core import cml, das, forecast, risk
from arlan_core.alerts import AlertEngine
from arlan_core.briefing import briefing_text

from . import db

CFG = json.loads((Path(__file__).resolve().parents[1] / "config" / "city.json").read_text())


def put_reading(kind: str, source: str, ts, data: dict):
    db.insert_row(db.readings, kind=kind, source=source, ts=ts, data=json.dumps(data, ensure_ascii=False))


def get_readings(kind, source=None, since=None, limit=5000):
    t = db.readings
    stmt = db.select(t).where(t.c.kind == kind)
    if source:
        stmt = stmt.where(t.c.source == source)
    if since is not None:
        stmt = stmt.where(t.c.ts >= since)
    stmt = stmt.order_by(t.c.ts.desc()).limit(limit)
    out = []
    for r in reversed(db.fetch_all(stmt)):
        out.append((r["ts"], r["source"], db.jload(r["data"], {})))
    return out


class Situation:
    def __init__(self, cfg=CFG):
        self.cfg = cfg
        self.segments = [das.Segment(s["id"], s["das"][0], s["das"][1]) for s in cfg["segments"]]
        self.n_channels = max(s["das"][1] for s in cfg["segments"]) + 1
        self.das_buf: list[np.ndarray] = []
        self.das_det = None
        self.das_scores: dict = {}
        self.links = {l["id"]: cml.Link(l["id"], l["freq_ghz"], l["length_km"], l.get("pol", "V")) for l in cfg["cml_links"]}
        self.alerts = AlertEngine(cfg)
        self.model = forecast.SnowmeltBaseline()

    def add_das(self, e: np.ndarray):
        self.das_buf = (self.das_buf + [e])[-96:]
        nb = self.cfg.get("das_baseline_windows", 24)
        if self.das_det is None and len(self.das_buf) >= nb:
            self.das_det = das.DASDetector().fit(np.stack(self.das_buf[:nb]))
        if self.das_det is not None:
            self.das_scores = self.das_det.segment_scores(np.stack(self.das_buf[-6:]), self.segments)

    def levels(self, hours=72):
        since = db.now() - timedelta(hours=hours)
        pts = []
        for ts, src, d in get_readings("gnss", since=since):
            if d.get("mode") == "water" and d.get("water_level_m") is not None and d.get("ok", True):
                pts.append((ts, d["water_level_m"], src))
        for ts, src, d in get_readings("level", since=since):
            pts.append((ts, d["level_m"], src))
        pts.sort(key=lambda p: p[0])
        return pts

    def swe(self):
        dens = self.cfg.get("snow_density_kg_m3", 250)
        vals, per = [], []
        for st in self.cfg["stations"]:
            if st["mode"] != "snow":
                continue
            r = get_readings("gnss", source=st["id"], limit=1)
            if r and r[-1][2].get("snow_depth_m") is not None:
                depth = r[-1][2]["snow_depth_m"]
                vals.append(depth * dens)
                per.append({"station": st["id"], "snow_depth_m": depth, "swe_mm": round(depth * dens, 1)})
        return (float(np.mean(vals)) if vals else 0.0), per

    def rain(self):
        out = {}
        since = db.now() - timedelta(hours=12)
        for lid, link in self.links.items():
            rs = get_readings("cml", source=lid, since=since)
            if len(rs) < 10:
                continue
            r = cml.rain_rate(np.array([d["tsl_dbm"] for *_, d in rs]), np.array([d["rsl_dbm"] for *_, d in rs]), link)
            out[lid] = {"rain_mm_h": round(float(r["rain_mm_h"][-1]), 1),
                        "rain_max_3h_mm_h": round(float(r["rain_mm_h"][-180:].max()), 1), "wet": bool(r["wet"][-1])}
        return out

    def state(self, temp_delta=0.0, release_extra=None, swe_mult=1.0, breach=None) -> dict:
        cfg = self.cfg
        lv = self.levels()
        level_now = lv[-1][1] if lv else cfg["base_level_m"]
        from datetime import datetime
        def t(x): return datetime.fromisoformat(x) if isinstance(x, str) else x
        day_ago = [p for p in lv if t(p[0]) <= db.now() - timedelta(hours=20)]
        rise = 0.0
        if day_ago:
            dt = (t(lv[-1][0]) - t(day_ago[-1][0])).total_seconds() / 86400
            rise = (level_now - day_ago[-1][1]) / max(dt, 1e-6)
        swe, snow = self.swe()
        w = get_readings("weather", limit=1)
        temps = list(w[-1][2].get("temp_forecast_c", [0.0] * 15)) if w else [0.0] * 15
        rel = list(w[-1][2].get("reservoir_extra_release_m3s") or [0.0] * 15) if w else [0.0] * 15
        temps = [x + temp_delta for x in temps[:15]]
        if release_extra is not None:
            rel = [r + release_extra for r in rel[:15]]
        fc = self.model.run(level_now, cfg["base_level_m"], swe * swe_mult, temps, rel[:15])
        ext = get_readings("external_forecast", limit=1)
        segs = []
        for s in cfg["segments"]:
            pz = get_readings("dam_sensor", source=s["id"], limit=1)
            das_score = self.das_scores.get(s["id"], {}).get("score", 0.0)
            crest = s["crest_m"]
            if breach and breach == s["id"]:
                crest = level_now - 0.1  # scenario: this segment fails
                das_score = 1.0
            r = risk.score(risk.SegmentInput(id=s["id"], crest_m=crest, level_now_m=level_now,
                                             level_p90_max_m=max(fc["p90"]), rise_m_per_day=rise,
                                             das_score=das_score,
                                             piezo_ratio=pz[-1][2].get("phreatic_ratio") if pz else None,
                                             age_years=s.get("age_years")))
            r.update(name=s["name"], district=s["district"], das=self.das_scores.get(s["id"], {}), crest_m=s["crest_m"])
            segs.append(r)
        st = {
            "generated_at": db.now().isoformat(), "city": cfg["city"], "river": cfg["river"],
            "level": {"now_m": round(level_now, 3), "rise_m_per_day": round(rise, 3), "danger_m": cfg["danger_level_m"],
                      "series": [{"ts": (p[0] if isinstance(p[0], str) else p[0].isoformat()), "m": round(p[1], 3), "src": p[2]} for p in lv[-200:]]},
            "forecast": {"days": len(fc["p50"]), **fc, "external": ext[-1][2] if ext else None},
            "snow": {"swe_mm": round(swe, 1), "stations": snow},
            "segments": segs, "rain": self.rain(), "das_ready": self.das_det is not None,
        }
        st["alerts"] = self.alerts.evaluate(st) if breach is None else []
        st["briefing_ru"] = briefing_text(st, "ru")
        st["briefing_kk"] = briefing_text(st, "kk")
        return st


SITUATION = Situation()
