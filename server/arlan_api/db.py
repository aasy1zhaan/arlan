"""Database layer: SQLAlchemy Core, works with SQLite (dev) and Postgres (Render).

Set DATABASE_URL=postgresql+psycopg://... in production; default is a local SQLite file.
Flexible payloads are stored as JSON text so the schema stays portable.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import (Boolean, Column, DateTime, Float, ForeignKey, Integer, MetaData, String,
                        Table, Text, create_engine, insert, select, update)

ROOT = Path(__file__).resolve().parents[1]


def _url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        # Render gives postgres://; SQLAlchemy 2 wants postgresql+psycopg://
        if url.startswith("postgres://"):
            url = "postgresql+psycopg://" + url[len("postgres://"):]
        elif url.startswith("postgresql://") and "+psycopg" not in url:
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
        return url
    path = Path(os.environ.get("ARLAN_DB", ROOT / "data" / "arlan.db"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path}"


engine = create_engine(_url(), future=True, pool_pre_ping=True)
md = MetaData()


def now() -> datetime:
    return datetime.now(timezone.utc)


users = Table("users", md,
    Column("id", Integer, primary_key=True),
    Column("email", String(200), unique=True, nullable=False),
    Column("name", String(200), nullable=False),
    Column("password_hash", String(300), nullable=False),
    Column("role", String(50), nullable=False),
    Column("service", String(30)),          # emergency | ambulance | police (dispatchers, crews)
    Column("unit_id", Integer),             # crews: their unit
    Column("active", Boolean, default=True),
    Column("created_at", DateTime(timezone=True), default=now))

roles = Table("roles", md,
    Column("key", String(50), primary_key=True),
    Column("title", String(100), nullable=False),
    Column("permissions", Text, nullable=False),   # JSON list
    Column("builtin", Boolean, default=False))

audit = Table("audit", md,
    Column("id", Integer, primary_key=True),
    Column("ts", DateTime(timezone=True), default=now),
    Column("user_id", Integer),
    Column("user_name", String(200)),
    Column("action", String(100)),
    Column("target", String(200)),
    Column("data", Text))

readings = Table("readings", md,
    Column("id", Integer, primary_key=True),
    Column("kind", String(40), index=True),
    Column("source", String(80), index=True),
    Column("ts", DateTime(timezone=True), index=True),
    Column("data", Text))

units = Table("units", md,
    Column("id", Integer, primary_key=True),
    Column("callsign", String(60), nullable=False),
    Column("service", String(30), nullable=False),   # emergency | ambulance | police
    Column("kind", String(30), nullable=False),      # boat | rescue_truck | ambulance | patrol | amphibious
    Column("capacity", Integer, default=4),
    Column("lat", Float), Column("lon", Float),
    Column("status", String(20), default="available"),  # available | busy | offline
    Column("updated_at", DateTime(timezone=True), default=now))

sos = Table("sos", md,
    Column("id", Integer, primary_key=True),
    Column("public_token", String(40), unique=True),
    Column("created_at", DateTime(timezone=True), default=now),
    Column("updated_at", DateTime(timezone=True), default=now),
    Column("lat", Float), Column("lon", Float),
    Column("address", String(300)),
    Column("phone", String(40)), Column("name", String(120)),
    Column("people", Integer, default=1),
    Column("children", Integer, default=0),
    Column("elderly", Integer, default=0),
    Column("immobile", Boolean, default=False),
    Column("medical", Boolean, default=False),
    Column("medical_note", String(300)),
    Column("water", String(30)),            # none | ankle | knee | waist | chest | roof
    Column("crime", Boolean, default=False),
    Column("comment", Text),
    Column("photo", Text),                  # small data URL
    Column("priority", Integer, default=50),   # 0..100
    Column("priority_reason", String(300)),
    Column("services", Text),               # JSON list of services needed
    Column("status", String(20), default="new"),  # new | assigned | en_route | on_scene | resolved | cancelled
    Column("unit_id", Integer),
    Column("rescued", Integer, default=0),
    Column("incident_id", Integer))

incidents = Table("incidents", md,
    Column("id", Integer, primary_key=True),
    Column("created_at", DateTime(timezone=True), default=now),
    Column("title", String(300), nullable=False),
    Column("kind", String(40)),             # dam | flood | rain | sos | infrastructure
    Column("severity", String(20), default="medium"),
    Column("status", String(20), default="open"),   # open | in_progress | resolved
    Column("segment_id", String(20)),
    Column("district", String(40)),
    Column("assignee_id", Integer),
    Column("due_at", DateTime(timezone=True)),
    Column("created_by", Integer))

incident_events = Table("incident_events", md,
    Column("id", Integer, primary_key=True),
    Column("incident_id", Integer, ForeignKey("incidents.id"), index=True),
    Column("ts", DateTime(timezone=True), default=now),
    Column("user_name", String(200)),
    Column("text", Text))

notifications = Table("notifications", md,
    Column("id", Integer, primary_key=True),
    Column("created_at", DateTime(timezone=True), default=now),
    Column("title", String(300)),
    Column("text_ru", Text), Column("text_kk", Text),
    Column("districts", Text),              # JSON list
    Column("channels", Text),               # JSON list
    Column("status", String(20), default="draft"),  # draft | pending | approved | sent | rejected
    Column("created_by", Integer), Column("approved_by", Integer),
    Column("recipients", Integer, default=0),
    Column("sent_at", DateTime(timezone=True)))

subscribers = Table("subscribers", md,
    Column("id", Integer, primary_key=True),
    Column("district", String(40)),
    Column("phone", String(40)), Column("telegram_chat", String(60)),
    Column("lat", Float), Column("lon", Float))

scenarios = Table("scenarios", md,
    Column("id", Integer, primary_key=True),
    Column("created_at", DateTime(timezone=True), default=now),
    Column("name", String(200)),
    Column("params", Text), Column("result", Text),
    Column("created_by", Integer))

conversations = Table("conversations", md,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, index=True),
    Column("title", String(200)),
    Column("created_at", DateTime(timezone=True), default=now),
    Column("updated_at", DateTime(timezone=True), default=now))

messages = Table("messages", md,
    Column("id", Integer, primary_key=True),
    Column("conversation_id", Integer, ForeignKey("conversations.id"), index=True),
    Column("ts", DateTime(timezone=True), default=now),
    Column("role", String(20)),             # user | assistant
    Column("content", Text))                # JSON: Anthropic content blocks


def init():
    md.create_all(engine)


def row(r) -> dict | None:
    if r is None:
        return None
    d = dict(r._mapping)
    for k, v in list(d.items()):
        if isinstance(v, datetime):
            d[k] = (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).isoformat()
    return d


def rows(rs) -> list[dict]:
    return [row(r) for r in rs]


def jload(s, default=None):
    if s is None:
        return default
    try:
        return json.loads(s)
    except Exception:  # noqa: BLE001
        return default


def q(stmt):
    with engine.begin() as c:
        return c.execute(stmt)


def fetch_all(stmt) -> list[dict]:
    with engine.connect() as c:
        return rows(c.execute(stmt).fetchall())


def fetch_one(stmt) -> dict | None:
    with engine.connect() as c:
        return row(c.execute(stmt).first())


def insert_row(table, **vals) -> int:
    with engine.begin() as c:
        res = c.execute(insert(table).values(**vals))
        pk = res.inserted_primary_key[0] if res.inserted_primary_key else None
        return int(pk) if isinstance(pk, int) or (isinstance(pk, str) and pk.isdigit()) else pk


def update_row(table, id_col, id_val, **vals):
    with engine.begin() as c:
        c.execute(update(table).where(id_col == id_val).values(**vals))


__all__ = ["engine", "md", "init", "now", "q", "fetch_all", "fetch_one", "insert_row", "update_row",
           "jload", "select", "users", "roles", "audit", "readings", "units", "sos", "incidents",
           "incident_events", "notifications", "subscribers", "scenarios", "conversations", "messages"]
