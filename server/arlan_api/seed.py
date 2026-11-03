"""Demo seed: users for every role, emergency units, residents' SOS calls, incidents,
a pending alert, and a synthetic spring-flood run through all sensor modules.
Runs once (skips if demo users exist). Disable with ARLAN_SEED_DEMO=0."""
from __future__ import annotations

import json
import secrets
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np

from . import db
from .auth import hash_password
from .dispatch import triage
from .situation import CFG, SITUATION, put_reading

DEMO_PASSWORD = "arlan2026"

USERS = [
    ("admin@demo.arlan.kz", "Асылжан Абдуллаев", "admin", None),
    ("head@demo.arlan.kz", "Руководитель штаба", "head", None),
    ("duty@demo.arlan.kz", "Дежурный ДЧС СКО", "duty", None),
    ("dispatch112@demo.arlan.kz", "Диспетчер 112 (МЧС)", "dispatcher", "emergency"),
    ("dispatch103@demo.arlan.kz", "Диспетчер 103 (скорая)", "dispatcher", "ambulance"),
    ("dispatch102@demo.arlan.kz", "Диспетчер 102 (полиция)", "dispatcher", "police"),
    ("crew@demo.arlan.kz", "Бригада МЧС «Лодка-1»", "crew", "emergency"),
    ("engineer@demo.arlan.kz", "Инженер дамб", "engineer", None),
    ("hydro@demo.arlan.kz", "Гидролог", "hydrologist", None),
    ("undp@demo.arlan.kz", "Наблюдатель ПРООН", "observer", None),
]

UNITS = [  # callsign, service, kind, capacity, lat, lon
    ("Лодка-1", "emergency", "boat", 6, 54.8760, 69.1350),
    ("Лодка-2", "emergency", "boat", 6, 54.8890, 69.1050),
    ("Амфибия-1", "emergency", "amphibious", 10, 54.8720, 69.1480),
    ("ПСЧ-3", "emergency", "rescue_truck", 8, 54.8700, 69.1550),
    ("Скорая-12", "ambulance", "ambulance", 2, 54.8660, 69.1600),
    ("Скорая-07", "ambulance", "ambulance", 2, 54.8800, 69.1300),
    ("Скорая-21", "ambulance", "ambulance", 2, 54.8600, 69.1700),
    ("Патруль-5", "police", "patrol", 4, 54.8680, 69.1400),
    ("Патруль-9", "police", "patrol", 4, 54.8850, 69.1150),
]

SOS = [  # lat, lon, address, people, children, elderly, immobile, medical, note, water, crime, comment, minutes_ago
    (54.8812, 69.1160, "ул. Ущева, частный дом", 3, 1, 1, False, False, None, "waist", False, "Вода прибывает, мы на втором этаже", 9),
    (54.8800, 69.1210, "Подгора, ул. Береговая", 2, 0, 1, True, True, "Бабушка лежачая, диабет", "knee", False, "Нужна эвакуация и врач", 14),
    (54.8838, 69.0700, "Кожевенный, дачи", 4, 2, 0, False, False, None, "roof", False, "Сидим на крыше сарая", 4),
    (54.8862, 69.0920, "у объездной, дом 14", 1, 0, 0, False, True, "Порезал ногу, кровь", "ankle", False, None, 22),
    (54.9020, 69.1180, "Заречный, ул. Луговая", 5, 3, 0, False, False, None, "chest", False, "Дети, вода по грудь во дворе", 6),
    (54.8795, 69.1250, "Подгора, магазин", 1, 0, 0, False, False, None, "knee", True, "Мародёры в соседних домах", 18),
]


def seed_sensors():
    rng = np.random.default_rng(7)
    now = db.now().replace(minute=0, second=0, microsecond=0)
    for h in range(72, -1, -1):
        t = now - timedelta(hours=h)
        k = (72 - h) / 72
        level = 3.0 + 2.4 * k ** 1.6 + rng.normal(0, 0.015)
        for sid, off in (("PTR-ESIL-01", 0.0), ("PTR-ESIL-02", 0.04)):
            put_reading("gnss", sid, t, {"station_id": sid, "mode": "water", "ok": True, "water_level_m": round(level + off, 3),
                                         "reflector_height_m": round(8 - level - off, 3), "n_arcs": int(rng.integers(6, 14)), "quality": 0.8})
        for sid, d0 in (("PTR-SNOW-01", 0.62), ("PTR-SNOW-02", 0.55)):
            put_reading("gnss", sid, t, {"station_id": sid, "mode": "snow", "ok": True,
                                         "snow_depth_m": round(max(0, d0 * (1 - 0.45 * k) + rng.normal(0, 0.01)), 3), "n_arcs": 9, "quality": 0.75})
    put_reading("weather", "main", now, {"temp_forecast_c": [2, 4, 7, 9, 8, 6, 5, 7, 9, 10, 8, 6, 5, 4, 4],
                                         "reservoir_extra_release_m3s": [0, 0, 40, 60, 60, 40, 0, 0, 0, 0, 0, 0, 0, 0, 0]})
    put_reading("external_forecast", "tasqyn", now, {"source": "tasqyn", "p50": [round(5.4 + 0.12 * d - 0.006 * d * d, 2) for d in range(15)]})
    put_reading("dam_sensor", "RECH", now, {"segment_id": "RECH", "phreatic_ratio": 0.45})
    from arlan_core import cml, das
    for l in CFG["cml_links"]:
        link = cml.Link(l["id"], l["freq_ghz"], l["length_km"], l.get("pol", "V"))
        storm, peak = ((480, 560), 32.0) if l["id"] == "KC-0102" else ((500, 520), 3.0)
        tsl, rsl, _ = cml.synthetic_link(link, minutes=600, storm=storm, peak_mm_h=peak, seed=abs(hash(l["id"])) % 1000)
        t0 = now - timedelta(minutes=600)
        for i in range(600):
            put_reading("cml", l["id"], t0 + timedelta(minutes=i), {"tsl_dbm": float(tsl[i]), "rsl_dbm": float(rsl[i])})
    n_ch = SITUATION.n_channels
    for w in das.synthetic_features(n_t=24, n_ch=n_ch, seed=1):
        SITUATION.add_das(w)
    for w in das.synthetic_features(n_t=8, n_ch=n_ch, seed=2, leak_at=(800, 818), leak_from_t=0, leak_gain=25):
        SITUATION.add_das(w)


def seed_demo():
    if db.fetch_one(db.select(db.users).where(db.users.c.email == USERS[0][0])):
        if SITUATION.das_det is None:  # in-memory DAS state is lost on restart
            from arlan_core import das
            for w in das.synthetic_features(n_t=24, n_ch=SITUATION.n_channels, seed=1):
                SITUATION.add_das(w)
            for w in das.synthetic_features(n_t=8, n_ch=SITUATION.n_channels, seed=2, leak_at=(800, 818), leak_from_t=0, leak_gain=25):
                SITUATION.add_das(w)
        return
    unit_ids = []
    for cs, svc, kind, cap, lat, lon in UNITS:
        unit_ids.append(db.insert_row(db.units, callsign=cs, service=svc, kind=kind, capacity=cap, lat=lat, lon=lon,
                                      status="available", updated_at=db.now()))
    pw = hash_password(DEMO_PASSWORD)
    for email, name, role, svc in USERS:
        db.insert_row(db.users, email=email, name=name, role=role, service=svc, password_hash=pw, active=True,
                      unit_id=unit_ids[0] if role == "crew" else None, created_at=db.now())
    rng = np.random.default_rng(3)
    for d in CFG["districts"]:
        for _ in range(int(rng.integers(120, 420))):
            db.insert_row(db.subscribers, district=d["id"], phone="+7700" + str(rng.integers(1000000, 9999999)))
    for lat, lon, addr, ppl, ch, el, imm, med, mnote, water, crime, comment, ago in SOS:
        data = dict(lat=lat, lon=lon, address=addr, people=ppl, children=ch, elderly=el, immobile=imm, medical=med,
                    medical_note=mnote, water=water, crime=crime, comment=comment, phone="+7 705 " + str(rng.integers(100, 999)) + " 00 00")
        tri = triage(data)
        t = db.now() - timedelta(minutes=ago)
        db.insert_row(db.sos, public_token=secrets.token_urlsafe(16), created_at=t, updated_at=t, **data,
                      priority=tri["priority"], priority_reason=tri["priority_reason"], services=json.dumps(tri["services"]), status="new")
    # one call already being handled
    first = db.fetch_one(db.select(db.sos).where(db.sos.c.address == "Подгора, ул. Береговая"))
    db.update_row(db.sos, db.sos.c.id, first["id"], status="en_route", unit_id=unit_ids[4])
    db.update_row(db.units, db.units.c.id, unit_ids[4], status="busy")
    admin = db.fetch_one(db.select(db.users).where(db.users.c.role == "duty"))
    eng = db.fetch_one(db.select(db.users).where(db.users.c.role == "engineer"))
    iid = db.insert_row(db.incidents, created_at=db.now() - timedelta(hours=2), title="Фильтрация на дамбе ул. Ущева (сигнал оптоволокна)",
                        kind="dam", severity="high", segment_id="PODG", district="podgora", status="in_progress",
                        assignee_id=eng["id"], created_by=admin["id"])
    for txt, mins in (("Инцидент создан по тревоге FIBER EAR: 18 каналов с устойчивым шумом", 120),
                      ("Инженер выехал на участок", 95), ("Визуально: мокрое пятно на низовом откосе, ~3 м", 60)):
        db.insert_row(db.incident_events, incident_id=iid, ts=db.now() - timedelta(minutes=mins), user_name=eng["name"] if mins < 120 else admin["name"], text=txt)
    db.insert_row(db.incidents, created_at=db.now() - timedelta(hours=1), title="Подтопление улиц Подгоры после ливня", kind="rain",
                  severity="medium", district="podgora", status="open", created_by=admin["id"])
    db.insert_row(db.notifications, created_at=db.now() - timedelta(minutes=20), title="Угроза подтопления: Подгора",
                  text_ru="Жители Подгоры! По прогнозу ARLAN уровень Есиля поднимется выше 6 м в ближайшие 5 дней. Подготовьте документы, лекарства и запас воды. Следите за сообщениями ДЧС. Экстренный вызов: 112.",
                  text_kk="Подгора тұрғындары! ARLAN болжамы бойынша Есіл деңгейі алдағы 5 күнде 6 м-ден асады. Құжаттарды, дәрі-дәрмекті және су қорын дайындаңыздар. ТЖД хабарламаларын қадағалаңыздар. Шұғыл қоңырау: 112.",
                  districts=json.dumps(["podgora"]), channels=json.dumps(["telegram", "sms"]), status="pending", created_by=admin["id"])
    seed_sensors()
