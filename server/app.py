"""ARLAN platform API v2.

Run:  uvicorn app:app --host 0.0.0.0 --port 8000
Env:  DATABASE_URL (Postgres in prod, SQLite by default), ARLAN_JWT_SECRET, ARLAN_API_KEYS (sensors),
      ANTHROPIC_API_KEY (assistant), ARLAN_LLM_MODEL, ARLAN_CORS (comma list of site origins),
      ARLAN_SEED_DEMO=1 (demo users, units and SOS on first start), TELEGRAM_BOT_TOKEN.
"""
from __future__ import annotations

import json
import os
import secrets
from datetime import timedelta

import numpy as np
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from arlan_api import db
from arlan_api.api_helpers import OPEN, assign, sos_out, sos_query
from arlan_api.assistant import stream_reply, visible_messages
from arlan_api.auth import (BUILTIN_ROLES, PERMISSIONS, SERVICES, check_password, current_user, ensure_roles, has,
                            hash_password, log, make_token, public_user, require)
from arlan_api.dispatch import recommend, triage
from arlan_api.situation import CFG, SITUATION, put_reading

db.init()
ensure_roles()
if os.environ.get("ARLAN_SEED_DEMO", "1") == "1":
    from arlan_api.seed import seed_demo
    seed_demo()

app = FastAPI(title="ARLAN API", version="2.0.0")
origins = [o for o in os.environ.get("ARLAN_CORS", "*").split(",") if o]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False, allow_methods=["*"], allow_headers=["*"])


def parse_ts(ts):
    from datetime import datetime, timezone
    if not ts:
        return db.now()
    d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


# ================================================================== auth
class LoginIn(BaseModel):
    email: str
    password: str


@app.post("/api/v1/auth/login")
def login(m: LoginIn):
    u = db.fetch_one(db.select(db.users).where(db.users.c.email == m.email.strip().lower()))
    if not u or not u["active"] or not check_password(m.password, u["password_hash"]):
        raise HTTPException(401, "Неверная почта или пароль")
    log(u, "auth.login")
    return {"token": make_token(u), "user": public_user(u)}


@app.get("/api/v1/auth/demo-accounts")
def demo_accounts():
    if os.environ.get("ARLAN_SEED_DEMO", "1") != "1":
        return []
    out = []
    for u in db.fetch_all(db.select(db.users).where(db.users.c.email.like("%@demo.arlan.kz"))):
        out.append({"email": u["email"], "name": u["name"], "role": u["role"],
                    "role_title": BUILTIN_ROLES.get(u["role"], (u["role"],))[0], "service": SERVICES.get(u["service"] or "")})
    return out


@app.post("/api/v1/auth/demo/{email}")
def demo_login(email: str):
    if os.environ.get("ARLAN_SEED_DEMO", "1") != "1" or not email.endswith("@demo.arlan.kz"):
        raise HTTPException(404)
    u = db.fetch_one(db.select(db.users).where(db.users.c.email == email))
    if not u:
        raise HTTPException(404)
    log(u, "auth.demo_login")
    return {"token": make_token(u), "user": public_user(u)}


@app.get("/api/v1/auth/me")
def me(user=Depends(current_user)):
    return public_user(user)


# ================================================================== admin: users, roles, audit
class UserIn(BaseModel):
    email: str
    name: str
    role: str
    password: str | None = None
    service: str | None = None
    unit_id: int | None = None
    active: bool = True


@app.get("/api/v1/admin/users")
def list_users(user=Depends(require("user.manage"))):
    return [{k: v for k, v in u.items() if k != "password_hash"} for u in db.fetch_all(db.select(db.users).order_by(db.users.c.id))]


@app.post("/api/v1/admin/users")
def create_user(m: UserIn, user=Depends(require("user.manage"))):
    if not db.fetch_one(db.select(db.roles).where(db.roles.c.key == m.role)):
        raise HTTPException(400, "Нет такой роли")
    pw = m.password or secrets.token_urlsafe(9)
    uid = db.insert_row(db.users, email=m.email.lower(), name=m.name, role=m.role, service=m.service, unit_id=m.unit_id,
                        password_hash=hash_password(pw), active=m.active, created_at=db.now())
    log(user, "user.create", f"user:{uid}", {"email": m.email, "role": m.role})
    return {"id": uid, "temporary_password": None if m.password else pw}


@app.patch("/api/v1/admin/users/{uid}")
def edit_user(uid: int, m: UserIn, user=Depends(require("user.manage"))):
    vals = {"name": m.name, "role": m.role, "service": m.service, "unit_id": m.unit_id, "active": m.active}
    if m.password:
        vals["password_hash"] = hash_password(m.password)
    db.update_row(db.users, db.users.c.id, uid, **vals)
    log(user, "user.update", f"user:{uid}", {k: v for k, v in vals.items() if k != "password_hash"})
    return {"ok": True}


@app.get("/api/v1/admin/roles")
def list_roles(user=Depends(current_user)):
    return {"roles": [{**r, "permissions": db.jload(r["permissions"], [])} for r in db.fetch_all(db.select(db.roles))],
            "permissions": PERMISSIONS, "services": SERVICES}


class RoleIn(BaseModel):
    key: str
    title: str
    permissions: list[str]


@app.post("/api/v1/admin/roles")
def upsert_role(m: RoleIn, user=Depends(require("user.manage"))):
    bad = [p for p in m.permissions if p not in PERMISSIONS]
    if bad:
        raise HTTPException(400, f"Неизвестные права: {bad}")
    r = db.fetch_one(db.select(db.roles).where(db.roles.c.key == m.key))
    if r and r["builtin"]:
        raise HTTPException(400, "Встроенную роль менять нельзя, создайте свою")
    if r:
        db.update_row(db.roles, db.roles.c.key, m.key, title=m.title, permissions=json.dumps(m.permissions))
    else:
        db.insert_row(db.roles, key=m.key, title=m.title, permissions=json.dumps(m.permissions), builtin=False)
    log(user, "role.upsert", f"role:{m.key}", m.model_dump())
    return {"ok": True}


@app.get("/api/v1/admin/audit")
def get_audit(limit: int = 200, user=Depends(require("audit.view"))):
    return db.fetch_all(db.select(db.audit).order_by(db.audit.c.id.desc()).limit(min(limit, 1000)))


# ================================================================== situation & scenarios
@app.get("/api/v1/state")
def get_state(user=Depends(require("map.view"))):
    return SITUATION.state()


@app.get("/api/v1/config")
def get_config():
    c = dict(CFG)
    c.pop("api_keys", None)
    return c


class ScenarioIn(BaseModel):
    name: str = "Сценарий"
    temp_delta_c: float = 0.0
    release_extra_m3s: float | None = None
    snow_multiplier: float = 1.0
    breach_segment: str | None = None
    save: bool = False


@app.post("/api/v1/scenarios/run")
def run_scenario(m: ScenarioIn, user=Depends(require("scenario.run"))):
    st = SITUATION.state(temp_delta=m.temp_delta_c, release_extra=m.release_extra_m3s, swe_mult=m.snow_multiplier, breach=m.breach_segment)
    res = {"forecast": st["forecast"], "segments": st["segments"], "level": {k: st["level"][k] for k in ("now_m", "danger_m")}}
    if m.save:
        sid = db.insert_row(db.scenarios, created_at=db.now(), name=m.name, params=m.model_dump_json(),
                            result=json.dumps(res, ensure_ascii=False), created_by=user["id"])
        res["id"] = sid
        log(user, "scenario.save", f"scenario:{sid}", m.model_dump())
    return res


@app.get("/api/v1/scenarios")
def list_scenarios(user=Depends(require("scenario.run"))):
    out = []
    for s in db.fetch_all(db.select(db.scenarios).order_by(db.scenarios.c.id.desc()).limit(50)):
        r = db.jload(s["result"], {})
        out.append({"id": s["id"], "name": s["name"], "created_at": s["created_at"], "params": db.jload(s["params"], {}),
                    "peak_m": max(r.get("forecast", {}).get("p50", [0]))})
    return out


# ================================================================== public SOS (no login)
class SosIn(BaseModel):
    lat: float
    lon: float
    phone: str = Field(..., min_length=5, max_length=40)
    name: str | None = None
    address: str | None = None
    people: int = Field(1, ge=1, le=100)
    children: int = Field(0, ge=0, le=50)
    elderly: int = Field(0, ge=0, le=50)
    immobile: bool = False
    medical: bool = False
    medical_note: str | None = None
    water: str = "none"
    crime: bool = False
    comment: str | None = Field(None, max_length=2000)
    photo: str | None = Field(None, max_length=900_000)


_sos_rate: dict[str, list] = {}


@app.post("/api/v1/public/sos")
def create_sos(m: SosIn, request: Request):
    ip = request.client.host if request.client else "?"
    now = db.now()
    recent = [t for t in _sos_rate.get(ip, []) if (now - t).total_seconds() < 600]
    if len(recent) >= 5:
        raise HTTPException(429, "Слишком много вызовов с этого устройства. Если опасность сохраняется, звоните 112.")
    _sos_rate[ip] = recent + [now]
    tri = triage(m.model_dump())
    token = secrets.token_urlsafe(16)
    sid = db.insert_row(db.sos, public_token=token, created_at=now, updated_at=now, **m.model_dump(),
                        priority=tri["priority"], priority_reason=tri["priority_reason"],
                        services=json.dumps(tri["services"]), status="new")
    log(None, "sos.create", f"sos:{sid}", {"priority": tri["priority"], "services": tri["services"]})
    return {"id": sid, "token": token, "priority": tri["priority"], "services": [SERVICES[s] for s in tri["services"]]}


@app.get("/api/v1/public/sos/{token}")
def sos_status(token: str):
    s = db.fetch_one(db.select(db.sos).where(db.sos.c.public_token == token))
    if not s:
        raise HTTPException(404)
    unit = db.fetch_one(db.select(db.units).where(db.units.c.id == s["unit_id"])) if s["unit_id"] else None
    eta = None
    if unit and unit["lat"] is not None:
        from arlan_api.dispatch import haversine_km
        d = haversine_km(s["lat"], s["lon"], unit["lat"], unit["lon"])
        eta = round(d * 1.35 / (18 if unit["kind"] in ("boat", "amphibious") else 30) * 60)
    return {"id": s["id"], "status": s["status"], "created_at": s["created_at"],
            "unit": {"callsign": unit["callsign"], "kind": unit["kind"], "lat": unit["lat"], "lon": unit["lon"]} if unit else None,
            "eta_min": eta}


@app.get("/api/v1/public/risk")
def public_risk(lat: float, lon: float):
    """For residents: nearest dam segment risk and the forecast peak (no personal data)."""
    st = SITUATION.state()
    from arlan_api.dispatch import haversine_km
    best, bd = None, 1e9
    for seg in CFG["segments"]:
        d = min(haversine_km(lat, lon, p[1], p[0]) for p in seg.get("geo", [])) if seg.get("geo") else 1e9
        if d < bd:
            best, bd = seg, d
    seg_state = next((s for s in st["segments"] if best and s["segment_id"] == best["id"]), None)
    return {"nearest_dam": best["name"] if best else None, "distance_km": round(bd, 2) if best else None,
            "risk": seg_state["risk"] if seg_state else None, "level_ru": seg_state["level_ru"] if seg_state else None,
            "peak_m": max(st["forecast"]["p50"]), "danger_m": st["level"]["danger_m"],
            "shelters": CFG.get("shelters", [])}


# ================================================================== dispatch (SOS queue, units)
@app.get("/api/v1/sos")
def list_sos(status: str = "open", user=Depends(require("sos.view"))):
    items = sos_query(user, status)
    units = db.fetch_all(db.select(db.units))
    svc = user.get("service") if user["role"] == "dispatcher" else None
    for s in items:
        if s["status"] == "new":
            s["recommended"] = [{k: u[k] for k in ("id", "callsign", "kind", "service", "eta_min", "distance_km", "why")}
                                for u in recommend(s, units, svc)]
    return items


@app.get("/api/v1/sos/{sid}")
def get_sos(sid: int, user=Depends(require("sos.view"))):
    s = db.fetch_one(db.select(db.sos).where(db.sos.c.id == sid))
    if not s:
        raise HTTPException(404)
    return sos_out(s)


class AssignIn(BaseModel):
    unit_id: int


@app.post("/api/v1/sos/{sid}/assign")
def assign_sos(sid: int, m: AssignIn, user=Depends(require("sos.dispatch"))):
    try:
        return assign(sid, m.unit_id, user)
    except ValueError as e:
        raise HTTPException(400, str(e))


class SosStatusIn(BaseModel):
    status: str
    rescued: int | None = None
    note: str | None = None


@app.post("/api/v1/sos/{sid}/status")
def sos_set_status(sid: int, m: SosStatusIn, user=Depends(current_user)):
    s = db.fetch_one(db.select(db.sos).where(db.sos.c.id == sid))
    if not s:
        raise HTTPException(404)
    own = user["role"] == "crew" and s["unit_id"] == user.get("unit_id")
    if not (own or has(user, "sos.dispatch")):
        raise HTTPException(403, "Нет прав менять статус этого вызова")
    if m.status not in ("en_route", "on_scene", "resolved", "cancelled", "new"):
        raise HTTPException(400, "Неизвестный статус")
    vals = {"status": m.status, "updated_at": db.now()}
    if m.rescued is not None:
        vals["rescued"] = m.rescued
    if m.status in ("resolved", "cancelled", "new") and s["unit_id"]:
        db.update_row(db.units, db.units.c.id, s["unit_id"], status="available", updated_at=db.now())
        if m.status == "new":
            vals["unit_id"] = None
    db.update_row(db.sos, db.sos.c.id, sid, **vals)
    log(user, "sos.status", f"sos:{sid}", m.model_dump())
    return sos_out(db.fetch_one(db.select(db.sos).where(db.sos.c.id == sid)))


@app.get("/api/v1/units")
def list_units(user=Depends(current_user)):
    if not (has(user, "unit.view") or has(user, "unit.self")):
        raise HTTPException(403)
    us = db.fetch_all(db.select(db.units).order_by(db.units.c.service, db.units.c.callsign))
    if not has(user, "unit.view"):
        us = [u for u in us if u["id"] == user.get("unit_id")]
    return us


class PosIn(BaseModel):
    lat: float
    lon: float
    status: str | None = None


@app.post("/api/v1/units/{uid}/position")
def unit_position(uid: int, m: PosIn, user=Depends(current_user)):
    if not ((user["role"] == "crew" and user.get("unit_id") == uid) or has(user, "sos.dispatch")):
        raise HTTPException(403)
    vals = {"lat": m.lat, "lon": m.lon, "updated_at": db.now()}
    if m.status in ("available", "busy", "offline"):
        vals["status"] = m.status
    db.update_row(db.units, db.units.c.id, uid, **vals)
    return {"ok": True}


@app.get("/api/v1/my-task")
def my_task(user=Depends(require("unit.self"))):
    unit = db.fetch_one(db.select(db.units).where(db.units.c.id == user.get("unit_id"))) if user.get("unit_id") else None
    task = db.fetch_one(db.select(db.sos).where(db.sos.c.unit_id == user.get("unit_id")).where(db.sos.c.status.in_(OPEN))) if unit else None
    return {"unit": unit, "task": sos_out(task) if task else None}


# ================================================================== incidents
class IncidentIn(BaseModel):
    title: str
    kind: str = "flood"
    severity: str = "medium"
    segment_id: str | None = None
    district: str | None = None
    assignee_id: int | None = None
    note: str | None = None


@app.get("/api/v1/incidents")
def list_incidents(status: str = "open", user=Depends(require("incident.view"))):
    t = db.incidents
    stmt = db.select(t).order_by(t.c.id.desc())
    if status == "open":
        stmt = stmt.where(t.c.status != "resolved")
    items = db.fetch_all(stmt.limit(200))
    names = {u["id"]: u["name"] for u in db.fetch_all(db.select(db.users.c.id, db.users.c.name))}
    for i in items:
        i["assignee"] = names.get(i["assignee_id"])
        i["events"] = db.fetch_all(db.select(db.incident_events).where(db.incident_events.c.incident_id == i["id"]).order_by(db.incident_events.c.id))
    return items


@app.post("/api/v1/incidents")
def create_incident(m: IncidentIn, user=Depends(require("incident.manage"))):
    iid = db.insert_row(db.incidents, created_at=db.now(), title=m.title, kind=m.kind, severity=m.severity, segment_id=m.segment_id,
                        district=m.district, assignee_id=m.assignee_id, status="open", created_by=user["id"])
    db.insert_row(db.incident_events, incident_id=iid, ts=db.now(), user_name=user["name"], text=m.note or "Инцидент создан")
    log(user, "incident.create", f"incident:{iid}", m.model_dump())
    return {"id": iid}


class IncidentUpd(BaseModel):
    status: str | None = None
    assignee_id: int | None = None
    severity: str | None = None
    note: str | None = None


@app.patch("/api/v1/incidents/{iid}")
def update_incident(iid: int, m: IncidentUpd, user=Depends(require("incident.manage"))):
    vals = {k: v for k, v in m.model_dump().items() if v is not None and k != "note"}
    if vals:
        db.update_row(db.incidents, db.incidents.c.id, iid, **vals)
    txt = m.note or ", ".join(f"{k}: {v}" for k, v in vals.items())
    if txt:
        db.insert_row(db.incident_events, incident_id=iid, ts=db.now(), user_name=user["name"], text=txt)
    log(user, "incident.update", f"incident:{iid}", m.model_dump())
    return {"ok": True}


# ================================================================== notifications with approval
class NotifIn(BaseModel):
    title: str
    text_ru: str
    text_kk: str = ""
    districts: list[str]
    channels: list[str] = ["telegram", "sms"]


def _recipients(districts):
    return len(db.fetch_all(db.select(db.subscribers.c.id).where(db.subscribers.c.district.in_(districts))))


@app.get("/api/v1/notifications")
def list_notifs(user=Depends(require("alert.prepare"))):
    out = []
    for n in db.fetch_all(db.select(db.notifications).order_by(db.notifications.c.id.desc()).limit(100)):
        n["districts"] = db.jload(n["districts"], [])
        n["channels"] = db.jload(n["channels"], [])
        n["recipients_est"] = _recipients(n["districts"])
        out.append(n)
    return out


@app.post("/api/v1/notifications")
def create_notif(m: NotifIn, user=Depends(require("alert.prepare"))):
    nid = db.insert_row(db.notifications, created_at=db.now(), title=m.title, text_ru=m.text_ru, text_kk=m.text_kk,
                        districts=json.dumps(m.districts), channels=json.dumps(m.channels), status="pending", created_by=user["id"])
    log(user, "alert.prepare", f"notification:{nid}", m.model_dump())
    return {"id": nid, "status": "pending"}


class Decision(BaseModel):
    approve: bool


@app.post("/api/v1/notifications/{nid}/decide")
def decide_notif(nid: int, m: Decision, user=Depends(require("alert.approve"))):
    n = db.fetch_one(db.select(db.notifications).where(db.notifications.c.id == nid))
    if not n or n["status"] != "pending":
        raise HTTPException(400, "Оповещение не ждёт утверждения")
    if not m.approve:
        db.update_row(db.notifications, db.notifications.c.id, nid, status="rejected", approved_by=user["id"])
        log(user, "alert.reject", f"notification:{nid}")
        return {"status": "rejected"}
    districts = db.jload(n["districts"], [])
    count = _recipients(districts)
    _send_telegram(n, districts)
    db.update_row(db.notifications, db.notifications.c.id, nid, status="sent", approved_by=user["id"], recipients=count, sent_at=db.now())
    log(user, "alert.approve_send", f"notification:{nid}", {"recipients": count})
    return {"status": "sent", "recipients": count}


def _send_telegram(n, districts):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        return
    import requests
    chats = {d["id"]: d.get("telegram_chat") for d in CFG["districts"]}
    for d in districts:
        if chats.get(d):
            try:
                requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                              json={"chat_id": chats[d], "text": f"ARLAN | {n['title']}\n{n['text_ru']}\n\n{n['text_kk'] or ''}"}, timeout=10)
            except Exception:  # noqa: BLE001
                pass


# ================================================================== assistant
class ConvIn(BaseModel):
    title: str | None = None


class MsgIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=8000)
    context: str | None = None
    image: str | None = Field(None, max_length=3_000_000, description="data:image/...;base64,...")


@app.get("/api/v1/chat")
def list_convs(user=Depends(require("assistant.use"))):
    return db.fetch_all(db.select(db.conversations).where(db.conversations.c.user_id == user["id"]).order_by(db.conversations.c.updated_at.desc()))


@app.post("/api/v1/chat")
def new_conv(m: ConvIn, user=Depends(require("assistant.use"))):
    cid = db.insert_row(db.conversations, user_id=user["id"], title=m.title or "Новый чат", created_at=db.now(), updated_at=db.now())
    return {"id": cid}


def _own_conv(cid, user):
    c = db.fetch_one(db.select(db.conversations).where(db.conversations.c.id == cid))
    if not c or c["user_id"] != user["id"]:
        raise HTTPException(404)
    return c


@app.get("/api/v1/chat/{cid}")
def get_conv(cid: int, user=Depends(require("assistant.use"))):
    c = _own_conv(cid, user)
    return {**c, "messages": visible_messages(cid)}


@app.delete("/api/v1/chat/{cid}")
def del_conv(cid: int, user=Depends(require("assistant.use"))):
    _own_conv(cid, user)
    db.q(db.messages.delete().where(db.messages.c.conversation_id == cid))
    db.q(db.conversations.delete().where(db.conversations.c.id == cid))
    return {"ok": True}


@app.post("/api/v1/chat/{cid}/send")
def send(cid: int, m: MsgIn, user=Depends(require("assistant.use"))):
    c = _own_conv(cid, user)
    content = [{"type": "text", "text": m.text}]
    if m.image and m.image.startswith("data:image/"):
        head, b64 = m.image.split(",", 1)
        content.insert(0, {"type": "image", "source": {"type": "base64", "media_type": head[5:].split(";")[0], "data": b64}})
    db.insert_row(db.messages, conversation_id=cid, ts=db.now(), role="user", content=json.dumps(content, ensure_ascii=False))
    if c["title"] in (None, "", "Новый чат"):
        db.update_row(db.conversations, db.conversations.c.id, cid, title=m.text[:60])
    return StreamingResponse(stream_reply(cid, user, m.context), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ================================================================== sensor ingest (API key)
def api_key(x_api_key: str = Header(default="")):
    keys = os.environ.get("ARLAN_API_KEYS")
    allowed = keys.split(",") if keys else CFG.get("api_keys", [])
    if allowed and x_api_key not in allowed:
        raise HTTPException(401, "bad API key")


class GnssIn(BaseModel):
    station_id: str
    ts: str | None = None
    mode: str = "water"
    ok: bool = True
    reflector_height_m: float | None = None
    rh_std_m: float | None = None
    water_level_m: float | None = None
    snow_depth_m: float | None = None
    n_arcs: int = 0
    quality: float = 0.0
    device: dict | None = None


@app.post("/api/v1/ingest/gnss", dependencies=[Depends(api_key)])
def ingest_gnss(m: GnssIn):
    put_reading("gnss", m.station_id, parse_ts(m.ts), m.model_dump())
    return {"ok": True}


class LevelIn(BaseModel):
    source: str
    ts: str | None = None
    level_m: float


@app.post("/api/v1/ingest/level", dependencies=[Depends(api_key)])
def ingest_level(m: LevelIn):
    put_reading("level", m.source, parse_ts(m.ts), m.model_dump())
    return {"ok": True}


class DasIn(BaseModel):
    ts: str | None = None
    energies: list[list[float]]


@app.post("/api/v1/ingest/das", dependencies=[Depends(api_key)])
def ingest_das(m: DasIn):
    e = np.array(m.energies, dtype=float)
    if e.ndim != 2 or e.shape[0] < SITUATION.n_channels:
        raise HTTPException(422, f"need energies[{SITUATION.n_channels}][bands]")
    SITUATION.add_das(e[: SITUATION.n_channels])
    return {"ok": True, "das_ready": SITUATION.das_det is not None, "scores": SITUATION.das_scores}


class CmlSample(BaseModel):
    ts: str | None = None
    tsl_dbm: float
    rsl_dbm: float


class CmlIn(BaseModel):
    link_id: str
    samples: list[CmlSample]


@app.post("/api/v1/ingest/cml", dependencies=[Depends(api_key)])
def ingest_cml(m: CmlIn):
    if m.link_id not in SITUATION.links:
        raise HTTPException(404, "unknown link")
    for s in m.samples:
        put_reading("cml", m.link_id, parse_ts(s.ts), s.model_dump())
    return {"ok": True, "n": len(m.samples)}


class DamSensorIn(BaseModel):
    segment_id: str
    ts: str | None = None
    phreatic_ratio: float | None = None
    tilt_deg: float | None = None
    moisture: float | None = None


@app.post("/api/v1/ingest/dam_sensor", dependencies=[Depends(api_key)])
def ingest_dam(m: DamSensorIn):
    put_reading("dam_sensor", m.segment_id, parse_ts(m.ts), m.model_dump())
    return {"ok": True}


class WeatherIn(BaseModel):
    ts: str | None = None
    temp_forecast_c: list[float]
    swe_mm: float | None = None
    reservoir_extra_release_m3s: list[float] | None = None


@app.post("/api/v1/ingest/weather", dependencies=[Depends(api_key)])
def ingest_weather(m: WeatherIn):
    put_reading("weather", "main", parse_ts(m.ts), m.model_dump())
    return {"ok": True}


class ExternalIn(BaseModel):
    source: str
    ts: str | None = None
    p50: list[float]


@app.post("/api/v1/ingest/external_forecast", dependencies=[Depends(api_key)])
def ingest_external(m: ExternalIn):
    put_reading("external_forecast", m.source, parse_ts(m.ts), m.model_dump())
    return {"ok": True}


@app.get("/api/v1/health")
def health():
    return {"ok": True, "time": db.now().isoformat(), "ai": bool(os.environ.get("ANTHROPIC_API_KEY"))}
