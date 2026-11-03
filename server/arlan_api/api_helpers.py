"""Shared operations used by both the REST API and the assistant tools."""
from __future__ import annotations

from . import db
from .auth import has, log

OPEN = ("new", "assigned", "en_route", "on_scene")


def sos_out(s: dict) -> dict:
    s = dict(s)
    s["services"] = db.jload(s.get("services"), [])
    s.pop("public_token", None)
    return s


def sos_query(user: dict, status: str = "open", service: str | None = None) -> list[dict]:
    t = db.sos
    stmt = db.select(t)
    if status == "open":
        stmt = stmt.where(t.c.status.in_(OPEN))
    elif status and status != "all":
        stmt = stmt.where(t.c.status == status)
    items = [sos_out(s) for s in db.fetch_all(stmt.order_by(t.c.priority.desc(), t.c.created_at))]
    # dispatchers see their own service; crews see only their assignment
    if user["role"] == "crew":
        items = [s for s in items if s.get("unit_id") == user.get("unit_id")]
    elif not has(user, "sos.view_all") and user.get("service"):
        items = [s for s in items if user["service"] in s["services"]]
    if service:
        items = [s for s in items if service in s["services"]]
    return items


def assign(sos_id: int, unit_id: int, user: dict) -> dict:
    s = db.fetch_one(db.select(db.sos).where(db.sos.c.id == sos_id))
    u = db.fetch_one(db.select(db.units).where(db.units.c.id == unit_id))
    if not s or not u:
        raise ValueError("SOS или бригада не найдены")
    if user["role"] == "dispatcher" and user.get("service") != u["service"]:
        raise ValueError("Диспетчер может назначать только бригады своей службы")
    if u["status"] != "available":
        raise ValueError(f"Бригада {u['callsign']} занята")
    if s["unit_id"]:  # release the previous unit
        db.update_row(db.units, db.units.c.id, s["unit_id"], status="available", updated_at=db.now())
    db.update_row(db.sos, db.sos.c.id, sos_id, unit_id=unit_id, status="assigned", updated_at=db.now())
    db.update_row(db.units, db.units.c.id, unit_id, status="busy", updated_at=db.now())
    log(user, "sos.assign", f"sos:{sos_id}", {"unit": u["callsign"]})
    return sos_out(db.fetch_one(db.select(db.sos).where(db.sos.c.id == sos_id)))
