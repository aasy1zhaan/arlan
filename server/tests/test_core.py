import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "firmware" / "gnss_station"))
os.environ["ARLAN_DB"] = str(Path(tempfile.mkdtemp()) / "t.db")

import gnssir  # noqa: E402
import station  # noqa: E402
from arlan_core import cml, das, forecast, risk  # noqa: E402


def test_gnssir_recovers_height():
    rng = np.random.default_rng(3)
    obs = []
    for i, (s, p) in enumerate([("GPS", 1), ("GPS", 8), ("GLONASS", 4), ("GALILEO", 11), ("BEIDOU", 6)]):
        obs += gnssir.simulate_arc(4.37, s, p, t0=i * 5000, rising=i % 2 == 0, rng=rng)
    r = gnssir.estimate(obs)
    assert r["ok"] and abs(r["reflector_height_m"] - 4.37) < 0.02


def test_gnssir_azimuth_mask_filters():
    obs = gnssir.simulate_arc(3.0, azim=50)
    s = gnssir.Settings(azimuth_mask=[[120, 240]])
    assert not gnssir.estimate(obs, s)["ok"]


def test_nmea_gsv_parse():
    body = "GLGSV,2,1,07,65,12,045,40,66,30,110,38,67,,,,74,05,320,33"
    cs = 0
    for ch in body:
        cs ^= ord(ch)
    obs = station.parse_gsv(f"${body}*{cs:02X}", 0.0)
    assert [o.prn for o in obs] == [65, 66, 74] and obs[0].system == "GLONASS"
    assert station.parse_gsv(f"${body}*00", 0.0) == []  # bad checksum


def test_das_finds_leak_and_ignores_traffic():
    det = das.DASDetector().fit(das.synthetic_features(n_t=24, seed=5))
    segs = [das.Segment("A", 0, 149), das.Segment("B", 150, 299), das.Segment("C", 300, 399)]
    leak = det.segment_scores(das.synthetic_features(leak_at=(200, 215)), segs)
    calm = det.segment_scores(das.synthetic_features(seed=11), segs)
    assert leak["B"]["score"] > 0.8 and leak["A"]["score"] < 0.2
    assert max(v["score"] for v in calm.values()) < 0.2


def test_cml_rain_total():
    link = cml.Link("x", 23, 2.5)
    tsl, rsl, true = cml.synthetic_link(link, peak_mm_h=25)
    r = cml.rain_rate(tsl, rsl, link)
    assert abs(r["rain_mm_h"].sum() - true.sum()) / true.sum() < 0.15


def test_forecast_and_risk_monotonic():
    m = forecast.SnowmeltBaseline()
    warm = m.run(4.0, 2.0, 120, [8] * 15)
    cold = m.run(4.0, 2.0, 120, [-5] * 15)
    assert max(warm["p50"]) > max(cold["p50"])
    lo = risk.score(risk.SegmentInput("s", 7.5, 4.0, 5.0, 0.1))
    hi = risk.score(risk.SegmentInput("s", 7.5, 6.8, 7.4, 0.4, das_score=0.9))
    assert hi["risk"] > lo["risk"] and hi["level"] in ("high", "critical")


def test_api_end_to_end():
    sys.path.insert(0, str(ROOT / "scripts"))
    import simulate
    st = simulate.run()
    worst = max(st["segments"], key=lambda s: s["risk"])
    assert worst["segment_id"] == "PODG"
    assert any(a["district"] == "podgora" for a in st["alerts"])
    from fastapi.testclient import TestClient
    import app
    c = TestClient(app.app)
    assert c.post("/api/v1/ingest/level", json={"source": "x", "level_m": 1}, headers={"X-API-Key": "bad"}).status_code == 401
    assert c.get("/api/v1/state").status_code == 401


def _h(c, email):
    return {"Authorization": "Bearer " + c.post(f"/api/v1/auth/demo/{email}").json()["token"]}


def test_rbac_and_dispatch():
    from fastapi.testclient import TestClient
    import app
    c = TestClient(app.app)
    d103 = _h(c, "dispatch103@demo.arlan.kz")
    assert c.get("/api/v1/admin/users", headers=d103).status_code == 403
    q = c.get("/api/v1/sos", headers=d103).json()
    assert q and all("ambulance" in s["services"] for s in q)          # 103 sees only medical calls
    d112 = _h(c, "dispatch112@demo.arlan.kz")
    deep = [s for s in c.get("/api/v1/sos", headers=d112).json() if s["water"] in ("roof", "chest") and s["status"] == "new"]
    assert deep and deep[0]["recommended"][0]["kind"] in ("boat", "amphibious")   # boats first on deep water
    amb = [u for u in c.get("/api/v1/units", headers=d112).json() if u["service"] == "ambulance" and u["status"] == "available"][0]
    assert c.post(f"/api/v1/sos/{deep[0]['id']}/assign", json={"unit_id": amb["id"]}, headers=d112).status_code == 400  # other service


def test_public_sos_and_alert_approval():
    from fastapi.testclient import TestClient
    import app
    c = TestClient(app.app)
    r = c.post("/api/v1/public/sos", json={"lat": 54.88, "lon": 69.11, "phone": "+77001112233", "water": "roof", "children": 2}).json()
    assert r["priority"] >= 80
    assert c.get(f"/api/v1/public/sos/{r['token']}").json()["status"] == "new"
    duty = _h(c, "duty@demo.arlan.kz")
    nid = c.post("/api/v1/notifications", json={"title": "t", "text_ru": "x", "districts": ["podgora"]}, headers=duty).json()["id"]
    assert c.post(f"/api/v1/notifications/{nid}/decide", json={"approve": True}, headers=duty).status_code == 403  # duty can't approve
    head = _h(c, "head@demo.arlan.kz")
    assert c.post(f"/api/v1/notifications/{nid}/decide", json={"approve": True}, headers=head).json()["status"] == "sent"
