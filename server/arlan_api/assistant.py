"""ARLAN assistant: Claude with tools over the platform's live data, streamed over SSE.

The assistant acts with the permissions of the signed-in user: a tool the role may not
use returns an error that Claude relays. Alerts are only DRAFTED (a human approves them).
"""
from __future__ import annotations

import json
import os
from datetime import timedelta, timezone

from . import db
from .auth import SERVICES, has, log
from .dispatch import WATER_RU, recommend
from .situation import SITUATION

MODEL = os.environ.get("ARLAN_LLM_MODEL", "claude-sonnet-5-5")
MAX_STEPS = 8

TOOLS = [
    {"name": "get_situation", "description": "Текущая обстановка: уровень Есиля, прогноз на 15 дней (P10/P50/P90), риск по каждому участку дамб с причинами, ливень по радиолиниям, снегозапас, активные тревоги.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "run_scenario", "description": "Сценарий «что если»: пересчитать прогноз и риски дамб при изменённых условиях. Возвращает пик уровня, день пика, риски участков.",
     "input_schema": {"type": "object", "properties": {
         "temp_delta_c": {"type": "number", "description": "Сдвиг прогноза температуры, °C (например +5 = резкое потепление)"},
         "release_extra_m3s": {"type": "number", "description": "Дополнительный сброс из Сергеевского водохранилища, м³/с, на каждый день"},
         "snow_multiplier": {"type": "number", "description": "Множитель снегозапаса (1.3 = на 30% больше снега)"},
         "breach_segment": {"type": "string", "enum": ["PODG", "KOZH", "RECH", "ZAR"], "description": "Смоделировать прорыв этого участка"}}}},
    {"name": "list_sos", "description": "Очередь SOS-вызовов жителей с приоритетом, координатами, составом людей, глубиной воды, статусом и назначенной бригадой.",
     "input_schema": {"type": "object", "properties": {
         "status": {"type": "string", "enum": ["open", "all", "new", "assigned", "en_route", "on_scene", "resolved"]},
         "service": {"type": "string", "enum": ["emergency", "ambulance", "police"]}}}},
    {"name": "list_units", "description": "Бригады служб (МЧС, скорая, полиция): тип техники, вместимость, положение, статус.",
     "input_schema": {"type": "object", "properties": {"service": {"type": "string", "enum": ["emergency", "ambulance", "police"]}}}},
    {"name": "recommend_units", "description": "Лучшие свободные бригады для SOS-вызова: по службе, типу техники для глубины воды и времени доезда.",
     "input_schema": {"type": "object", "properties": {"sos_id": {"type": "integer"}}, "required": ["sos_id"]}},
    {"name": "assign_unit", "description": "Назначить бригаду на SOS-вызов. Делать только по явной просьбе пользователя.",
     "input_schema": {"type": "object", "properties": {"sos_id": {"type": "integer"}, "unit_id": {"type": "integer"}}, "required": ["sos_id", "unit_id"]}},
    {"name": "list_incidents", "description": "Открытые инциденты с исполнителями и последними событиями.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "create_incident", "description": "Создать инцидент. Делать только по явной просьбе пользователя.",
     "input_schema": {"type": "object", "properties": {
         "title": {"type": "string"}, "kind": {"type": "string", "enum": ["dam", "flood", "rain", "sos", "infrastructure"]},
         "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
         "segment_id": {"type": "string"}, "district": {"type": "string"}, "note": {"type": "string"}}, "required": ["title", "kind", "severity"]}},
    {"name": "draft_alert", "description": "Подготовить оповещение жителям (RU и KZ). Оно уходит руководителю на утверждение, само не рассылается.",
     "input_schema": {"type": "object", "properties": {
         "title": {"type": "string"}, "text_ru": {"type": "string"}, "text_kk": {"type": "string"},
         "districts": {"type": "array", "items": {"type": "string", "enum": ["podgora", "kozhevenny", "kosogor", "zarechny", "center"]}}},
         "required": ["title", "text_ru", "districts"]}},
]


def _deny(perm):
    return {"error": f"У вашей роли нет права на это действие ({perm})."}


def run_tool(name: str, args: dict, user: dict) -> dict:
    if name == "get_situation":
        if not has(user, "map.view"):
            return _deny("map.view")
        st = SITUATION.state()
        fc = st["forecast"]
        return {"level_now_m": st["level"]["now_m"], "rise_m_per_day": st["level"]["rise_m_per_day"],
                "danger_level_m": st["level"]["danger_m"], "forecast_p50": fc["p50"], "forecast_p90": fc["p90"],
                "external_forecast": fc.get("external"), "snow_swe_mm": st["snow"]["swe_mm"], "rain": st["rain"],
                "segments": [{k: s[k] for k in ("segment_id", "name", "risk", "level_ru", "freeboard_now_m", "freeboard_forecast_m", "main_driver", "factors")} for s in st["segments"]],
                "alerts": [{k: a[k] for k in ("title", "text", "severity")} for a in st["alerts"]],
                "note": "Отметки дамб в демо-конфигурации условные."}
    if name == "run_scenario":
        if not has(user, "scenario.run"):
            return _deny("scenario.run")
        st = SITUATION.state(temp_delta=args.get("temp_delta_c", 0.0), release_extra=args.get("release_extra_m3s"),
                             swe_mult=args.get("snow_multiplier", 1.0), breach=args.get("breach_segment"))
        p = st["forecast"]["p50"]
        return {"params": args, "peak_m": max(p), "peak_day": p.index(max(p)) + 1, "p90_max_m": max(st["forecast"]["p90"]),
                "danger_level_m": st["level"]["danger_m"],
                "segments": [{"id": s["segment_id"], "name": s["name"], "risk": s["risk"], "level_ru": s["level_ru"],
                              "freeboard_forecast_m": s["freeboard_forecast_m"]} for s in st["segments"]]}
    if name == "list_sos":
        if not has(user, "sos.view"):
            return _deny("sos.view")
        from .api_helpers import sos_query
        return {"sos": [{k: s.get(k) for k in ("id", "priority", "priority_reason", "status", "lat", "lon", "address", "people",
                                                "children", "elderly", "immobile", "medical", "water", "services", "unit_id", "created_at")}
                        for s in sos_query(user, args.get("status", "open"), args.get("service"))]}
    if name == "list_units":
        if not has(user, "unit.view"):
            return _deny("unit.view")
        stmt = db.select(db.units)
        if args.get("service"):
            stmt = stmt.where(db.units.c.service == args["service"])
        return {"units": db.fetch_all(stmt)}
    if name == "recommend_units":
        if not has(user, "sos.view"):
            return _deny("sos.view")
        s = db.fetch_one(db.select(db.sos).where(db.sos.c.id == args["sos_id"]))
        if not s:
            return {"error": "SOS не найден"}
        s["services"] = db.jload(s["services"], [])
        svc = user.get("service") if user["role"] == "dispatcher" else None
        return {"sos_id": s["id"], "candidates": [{k: u[k] for k in ("id", "callsign", "service", "kind", "distance_km", "eta_min", "why")}
                                                  for u in recommend(s, db.fetch_all(db.select(db.units)), svc)]}
    if name == "assign_unit":
        if not has(user, "sos.dispatch"):
            return _deny("sos.dispatch")
        from .api_helpers import assign
        try:
            return {"ok": True, "sos": assign(args["sos_id"], args["unit_id"], user)}
        except ValueError as e:
            return {"error": str(e)}
    if name == "list_incidents":
        if not has(user, "incident.view"):
            return _deny("incident.view")
        inc = db.fetch_all(db.select(db.incidents).where(db.incidents.c.status != "resolved").order_by(db.incidents.c.id.desc()).limit(30))
        return {"incidents": inc}
    if name == "create_incident":
        if not has(user, "incident.manage"):
            return _deny("incident.manage")
        iid = db.insert_row(db.incidents, created_at=db.now(), title=args["title"], kind=args["kind"], severity=args["severity"],
                            segment_id=args.get("segment_id"), district=args.get("district"), status="open", created_by=user["id"])
        db.insert_row(db.incident_events, incident_id=iid, ts=db.now(), user_name=f"{user['name']} (через ИИ)",
                      text=args.get("note") or "Инцидент создан ассистентом по запросу пользователя")
        log(user, "incident.create.ai", f"incident:{iid}", args)
        return {"ok": True, "incident_id": iid}
    if name == "draft_alert":
        if not has(user, "alert.prepare"):
            return _deny("alert.prepare")
        nid = db.insert_row(db.notifications, created_at=db.now(), title=args["title"], text_ru=args["text_ru"],
                            text_kk=args.get("text_kk", ""), districts=json.dumps(args["districts"]),
                            channels=json.dumps(["telegram", "sms"]), status="pending", created_by=user["id"])
        log(user, "alert.draft.ai", f"notification:{nid}", args)
        return {"ok": True, "notification_id": nid, "status": "pending", "note": "Ждёт утверждения руководителем."}
    return {"error": f"Неизвестный инструмент {name}"}


def system_prompt(user: dict, context: str | None) -> str:
    almaty = db.now().astimezone(timezone(timedelta(hours=5))).strftime("%d.%m.%Y %H:%M")
    perms = ", ".join(user["permissions"])
    svc = SERVICES.get(user.get("service") or "", "")
    return (
        "Ты — ARLAN, ИИ-ассистент платформы раннего предупреждения о паводках в Петропавловске (река Есиль, Северо-Казахстанская область). "
        f"Сейчас {almaty} по Астане. Пользователь: {user['name']}, роль: {user['role']}{', служба: ' + svc if svc else ''}. Права: {perms}.\n"
        "Правила:\n"
        "- Цифры об обстановке бери только из инструментов, не выдумывай. Если данных нет — так и скажи.\n"
        "- Действия (назначить бригаду, создать инцидент, подготовить оповещение) выполняй только по явной просьбе. "
        "Оповещения ты только готовишь, рассылку утверждает руководитель.\n"
        "- Решения об эвакуации принимает человек; ты даёшь расчёт и рекомендацию.\n"
        "- Отвечай по-деловому и по сути, как опытный коллега-аналитик. Можно использовать списки и таблицы markdown.\n"
        "- Отвечай на языке пользователя (русский или казахский).\n"
        "- В демо-режиме данные датчиков синтетические, а отметки дамб условные: упоминай это, если речь о точных цифрах для решений.\n"
        + (f"Пользователь сейчас смотрит: {context}\n" if context else "")
    )


def stream_reply(conv_id: int, user: dict, context: str | None):
    """Generator of SSE strings. Stores the full exchange in the conversation."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        yield _sse({"type": "error", "text": "ИИ не подключён: на сервере не задан ANTHROPIC_API_KEY. Администратору нужно добавить ключ в настройки сервиса."})
        yield _sse({"type": "done"})
        return
    import anthropic
    client = anthropic.Anthropic(api_key=key)
    hist = db.fetch_all(db.select(db.messages).where(db.messages.c.conversation_id == conv_id).order_by(db.messages.c.id))
    msgs = [{"role": m["role"], "content": db.jload(m["content"], m["content"])} for m in hist]
    system = system_prompt(user, context)
    for _ in range(MAX_STEPS):
        try:
            with client.messages.stream(model=MODEL, max_tokens=2000, system=system, tools=TOOLS, messages=msgs) as s:
                for ev in s:
                    if ev.type == "content_block_delta" and getattr(ev.delta, "type", "") == "text_delta":
                        yield _sse({"type": "text", "delta": ev.delta.text})
                final = s.get_final_message()
        except Exception as e:  # noqa: BLE001
            yield _sse({"type": "error", "text": f"Ошибка ИИ: {e}"})
            break
        content = [b.model_dump(exclude_none=True) for b in final.content]
        msgs.append({"role": "assistant", "content": content})
        db.insert_row(db.messages, conversation_id=conv_id, ts=db.now(), role="assistant", content=json.dumps(content, ensure_ascii=False))
        if final.stop_reason != "tool_use":
            break
        results = []
        for b in final.content:
            if b.type == "tool_use":
                yield _sse({"type": "tool", "name": b.name, "input": b.input})
                out = run_tool(b.name, b.input or {}, user)
                yield _sse({"type": "tool_result", "name": b.name, "ok": "error" not in out})
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(out, ensure_ascii=False, default=str)})
        msgs.append({"role": "user", "content": results})
        db.insert_row(db.messages, conversation_id=conv_id, ts=db.now(), role="user", content=json.dumps(results, ensure_ascii=False))
    db.update_row(db.conversations, db.conversations.c.id, conv_id, updated_at=db.now())
    yield _sse({"type": "done"})


def _sse(obj) -> str:
    return "data: " + json.dumps(obj, ensure_ascii=False, default=str) + "\n\n"


def visible_messages(conv_id: int) -> list[dict]:
    """Conversation as the UI shows it: user text and assistant text, tool calls as chips."""
    out = []
    for m in db.fetch_all(db.select(db.messages).where(db.messages.c.conversation_id == conv_id).order_by(db.messages.c.id)):
        c = db.jload(m["content"], m["content"])
        if isinstance(c, str):
            out.append({"role": m["role"], "text": c, "tools": []})
            continue
        texts = [b.get("text", "") for b in c if b.get("type") == "text"]
        tools = [b.get("name") for b in c if b.get("type") == "tool_use"]
        if m["role"] == "user" and not texts:
            continue  # tool results
        if out and m["role"] == "assistant" and out[-1]["role"] == "assistant":
            out[-1]["text"] += "".join(texts)
            out[-1]["tools"] += tools
        else:
            out.append({"role": m["role"], "text": "".join(texts), "tools": tools})
    return out
