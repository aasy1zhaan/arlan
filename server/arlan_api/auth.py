"""Authentication (JWT) and role-based access control."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from datetime import timedelta

import jwt
from fastapi import Depends, Header, HTTPException

from . import db

SECRET = os.environ.get("ARLAN_JWT_SECRET") or secrets.token_hex(32)
TOKEN_HOURS = 12

# ---------------------------------------------------------------- permissions
PERMISSIONS = {
    "map.view": "Ситуационная карта и прогноз",
    "scenario.run": "Запуск сценариев «что если»",
    "incident.view": "Просмотр инцидентов",
    "incident.manage": "Создание и ведение инцидентов",
    "sos.view": "Очередь SOS своей службы",
    "sos.view_all": "Очередь SOS всех служб",
    "sos.dispatch": "Назначение бригад на SOS",
    "unit.view": "Бригады на карте",
    "unit.self": "Своя задача и статус бригады",
    "alert.prepare": "Подготовка оповещений",
    "alert.approve": "Утверждение и отправка оповещений",
    "dam.manage": "Паспорта дамб и осмотры",
    "device.view": "Парк датчиков",
    "report.view": "Отчёты и аналитика",
    "assistant.use": "ИИ-ассистент",
    "user.manage": "Пользователи и роли",
    "audit.view": "Журнал действий",
}

BUILTIN_ROLES = {
    "admin": ("Администратор", list(PERMISSIONS)),
    "head": ("Руководитель (аким, начальник ДЧС)",
             ["map.view", "scenario.run", "incident.view", "incident.manage", "sos.view", "sos.view_all",
              "unit.view", "alert.prepare", "alert.approve", "device.view", "report.view", "assistant.use", "audit.view"]),
    "duty": ("Дежурный ДЧС",
             ["map.view", "scenario.run", "incident.view", "incident.manage", "sos.view", "sos.view_all",
              "sos.dispatch", "unit.view", "alert.prepare", "device.view", "report.view", "assistant.use"]),
    "dispatcher": ("Диспетчер службы (112 / 103 / 102)",
                   ["map.view", "incident.view", "sos.view", "sos.dispatch", "unit.view", "assistant.use"]),
    "crew": ("Полевая бригада", ["map.view", "unit.self", "assistant.use"]),
    "engineer": ("Инженер дамб", ["map.view", "incident.view", "incident.manage", "dam.manage", "device.view", "assistant.use"]),
    "hydrologist": ("Гидролог / аналитик", ["map.view", "scenario.run", "device.view", "report.view", "assistant.use"]),
    "observer": ("Наблюдатель (ПРООН, партнёры)", ["map.view", "incident.view", "report.view"]),
}

SERVICES = {"emergency": "МЧС / 112", "ambulance": "Скорая / 103", "police": "Полиция / 102"}


# ---------------------------------------------------------------- passwords
def hash_password(pw: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 200_000).hex()
    return f"pbkdf2${salt}${h}"


def check_password(pw: str, stored: str) -> bool:
    try:
        _, salt, h = stored.split("$")
    except ValueError:
        return False
    calc = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 200_000).hex()
    return hmac.compare_digest(calc, h)


# ---------------------------------------------------------------- tokens
def make_token(user: dict) -> str:
    payload = {"sub": str(user["id"]), "role": user["role"], "exp": db.now() + timedelta(hours=TOKEN_HOURS)}
    return jwt.encode(payload, SECRET, algorithm="HS256")


def role_permissions(role_key: str) -> list[str]:
    r = db.fetch_one(db.select(db.roles).where(db.roles.c.key == role_key))
    return db.jload(r["permissions"], []) if r else []


def public_user(u: dict) -> dict:
    perms = role_permissions(u["role"])
    r = db.fetch_one(db.select(db.roles).where(db.roles.c.key == u["role"]))
    return {"id": u["id"], "email": u["email"], "name": u["name"], "role": u["role"],
            "role_title": r["title"] if r else u["role"], "service": u.get("service"),
            "service_title": SERVICES.get(u.get("service") or ""), "unit_id": u.get("unit_id"),
            "permissions": perms}


def current_user(authorization: str = Header(default="")) -> dict:
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Нужен вход")
    try:
        p = jwt.decode(authorization[7:], SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Сессия истекла, войдите снова")
    u = db.fetch_one(db.select(db.users).where(db.users.c.id == int(p["sub"])))
    if not u or not u["active"]:
        raise HTTPException(401, "Пользователь отключён")
    u["permissions"] = role_permissions(u["role"])
    return u


def require(*perms: str):
    def dep(user: dict = Depends(current_user)) -> dict:
        missing = [p for p in perms if p not in user["permissions"]]
        if missing:
            raise HTTPException(403, f"Нет прав: {', '.join(PERMISSIONS.get(m, m) for m in missing)}")
        return user
    return dep


def has(user: dict, perm: str) -> bool:
    return perm in user.get("permissions", [])


def log(user: dict | None, action: str, target: str = "", data: dict | None = None):
    db.insert_row(db.audit, ts=db.now(), user_id=(user or {}).get("id"),
                  user_name=(user or {}).get("name", "система"), action=action, target=target,
                  data=json.dumps(data or {}, ensure_ascii=False))


def ensure_roles():
    for key, (title, perms) in BUILTIN_ROLES.items():
        r = db.fetch_one(db.select(db.roles).where(db.roles.c.key == key))
        if r is None:
            db.insert_row(db.roles, key=key, title=title, permissions=json.dumps(perms), builtin=True)
        elif r["builtin"]:
            db.update_row(db.roles, db.roles.c.key, key, title=title, permissions=json.dumps(perms))
