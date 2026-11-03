"""SOS triage and unit recommendation for emergency services (112 / 103 / 102)."""
from __future__ import annotations

import math

WATER_SCORE = {"none": 0, "ankle": 5, "knee": 15, "waist": 35, "chest": 50, "roof": 60}
WATER_RU = {"none": "воды нет", "ankle": "по щиколотку", "knee": "по колено", "waist": "по пояс",
            "chest": "по грудь", "roof": "на крыше / чердаке"}
KIND_RU = {"boat": "лодка", "amphibious": "амфибия", "rescue_truck": "спасательная машина",
           "ambulance": "скорая", "patrol": "патруль"}
DEEP = {"waist", "chest", "roof"}


def triage(s: dict) -> dict:
    """Explainable priority 0..100 and the services the call needs."""
    score, why = 15, []
    w = s.get("water") or "none"
    if WATER_SCORE.get(w):
        score += WATER_SCORE[w]
        why.append(f"вода {WATER_RU.get(w, w)}")
    if s.get("immobile"):
        score += 15
        why.append("лежачий человек")
    if s.get("medical"):
        score += 20
        why.append("нужна медпомощь")
    k = int(s.get("children") or 0)
    if k:
        score += min(15, 5 * k)
        why.append(f"дети: {k}")
    e = int(s.get("elderly") or 0)
    if e:
        score += min(15, 5 * e)
        why.append(f"пожилые: {e}")
    if int(s.get("people") or 1) >= 4:
        score += 5
        why.append(f"людей: {s.get('people')}")
    if s.get("crime"):
        score += 10
        why.append("угроза безопасности")
    services = []
    if w in ("knee",) or w in DEEP or s.get("immobile") or not (s.get("medical") or s.get("crime")):
        services.append("emergency")
    if s.get("medical"):
        services.append("ambulance")
    if s.get("crime"):
        services.append("police")
    return {"priority": max(0, min(100, score)), "priority_reason": ", ".join(why) or "без отягчающих факторов",
            "services": services}


def haversine_km(a_lat, a_lon, b_lat, b_lon) -> float:
    r = 6371.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = p2 - p1, math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def recommend(s: dict, units: list[dict], service: str | None = None, top: int = 3) -> list[dict]:
    """Rank available units for an SOS: right service, right vehicle for the water depth, distance."""
    need = [service] if service else (s.get("services") or ["emergency"])
    deep = (s.get("water") or "none") in DEEP
    out = []
    for u in units:
        if u["status"] != "available" or u["service"] not in need or u["lat"] is None:
            continue
        d = haversine_km(s["lat"], s["lon"], u["lat"], u["lon"])
        speed = 18 if u["kind"] in ("boat", "amphibious") else 30
        eta = d * 1.35 / speed * 60
        penalty = 0.0
        if u["service"] == "emergency" and deep and u["kind"] not in ("boat", "amphibious"):
            penalty = 8.0  # a truck can't reach a roof in deep water
        if int(s.get("people") or 1) > int(u.get("capacity") or 4):
            penalty += 1.0
        out.append({**u, "distance_km": round(d, 2), "eta_min": round(eta), "score": round(eta + penalty * 10, 1),
                    "why": (f"{KIND_RU.get(u['kind'], u['kind'])}, {round(d, 1)} км, ~{round(eta)} мин"
                            + ("; нужна лодка на глубокой воде" if penalty >= 8 else ""))})
    out.sort(key=lambda x: x["score"])
    return out[:top]
