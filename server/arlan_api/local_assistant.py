"""Assistant without an LLM key: intent rules over the same tools Claude uses.

Every number in the reply comes from the platform's tools (no canned figures). The reply
streams word by word like the Claude mode and lists the data it consulted. When
ANTHROPIC_API_KEY is set, assistant.stream_reply uses Claude instead.
"""
from __future__ import annotations

import json
import re
import time

from . import db
from .auth import has

SEG_NAMES = {"PODG": ("подгор", "ущев"), "KOZH": ("кожев",), "RECH": ("речпорт", "объездн", "вал"), "ZAR": ("заречн",)}
DISTRICTS = {"podgora": ("подгор", "ущев"), "kozhevenny": ("кожев",), "kosogor": ("косогор",), "zarechny": ("заречн",), "center": ("центр",)}
DIST_RU = {"podgora": "Подгора", "kozhevenny": "Кожевенный", "kosogor": "Косогор", "zarechny": "Заречный", "center": "Центр"}
WATER = {"none": "воды нет", "ankle": "по щиколотку", "knee": "по колено", "waist": "по пояс", "chest": "по грудь", "roof": "на крыше"}
DRIVER = {"freeboard": "малый запас до гребня", "rise": "быстрый подъём воды", "das": "аномалия в оптоволокне (возможна фильтрация)",
          "piezo": "высокий уровень воды внутри дамбы", "age": "возраст сооружения"}


def _has(text, *words):
    return any(w in text for w in words)


def _num_near(text, keys, default=None):
    for k in keys:
        m = re.search(r"([+-]?\d+(?:[.,]\d+)?)\s*(?:" + k + ")", text) or re.search(k + r"\D{0,25}?([+-]?\d+(?:[.,]\d+)?)", text)
        if m:
            return float(m.group(1).replace(",", "."))
    return default


def _district(text):
    return [d for d, ws in DISTRICTS.items() if _has(text, *ws)]


def _segment(text):
    for s, ws in SEG_NAMES.items():
        if _has(text, *ws):
            return s
    return None


def plan(text: str, user: dict):
    """Return (list of (tool, args)), composer function name."""
    t = text.lower()
    if _has(t, "если", "сценари", "что будет", "сброс", "потепл", "м³", "м3/с", "м3"):
        args = {}
        rel = _num_near(t, [r"м³", r"м3", r"кубов", r"сброс"])
        if rel is not None:
            args["release_extra_m3s"] = abs(rel)
        temp = _num_near(t, [r"°", r"градус", r"потепл"])
        if temp is not None:
            args["temp_delta_c"] = temp
        pct = re.search(r"снег\D{0,30}?(\d+)\s*%|(\d+)\s*%\D{0,20}снег", t)
        if pct:
            args["snow_multiplier"] = 1 + float(pct.group(1) or pct.group(2)) / 100
        if _has(t, "прорыв", "прорвёт", "прорвет"):
            seg = _segment(t)
            if seg:
                args["breach_segment"] = seg
        return [("get_situation", {}), ("run_scenario", args)], "scenario"
    if _has(t, "назнач") and has(user, "sos.dispatch"):
        return [("list_sos", {}), ("list_units", {})], "assign"
    if _has(t, "оповещ", "предупред", "напиши жител", "сообщение жител", "рассылк"):
        return [("get_situation", {})], "alert"
    if _has(t, "спас", "sos", "сос", "вызов", "очеред", "кого", "эвакуац") and has(user, "sos.view"):
        return [("list_sos", {})], "sos"
    if _has(t, "бригад", "лодк", "скор", "патрул", "техник") and has(user, "unit.view"):
        return [("list_units", {})], "units"
    if _has(t, "инцидент") and has(user, "incident.view"):
        if _has(t, "созда", "заведи", "открой") and has(user, "incident.manage"):
            return [("get_situation", {})], "incident_create"
        return [("list_incidents", {})], "incidents"
    if _has(t, "дожд", "ливн", "осадк"):
        return [("get_situation", {})], "rain"
    if _has(t, "дамб", "участ", "опасн", "риск", "прорыв"):
        return [("get_situation", {})], "dams"
    if _has(t, "уровень", "прогноз", "пик", "есил", "вода подним"):
        return [("get_situation", {})], "level"
    if _has(t, "сводк", "доклад", "аким", "кратко", "обстановк", "ситуац", "что происходит"):
        return [("get_situation", {})], "brief"
    if _has(t, "привет", "салем", "сәлем", "здравств", "что умеешь", "помощь", "help"):
        return [], "hello"
    return [("get_situation", {})], "brief"


def compose(kind: str, text: str, res: dict, user: dict, run_tool) -> str:
    st = res.get("get_situation") or {}
    if kind == "hello":
        return ("Я ARLAN, ассистент штаба. Работаю с живыми данными платформы в пределах ваших прав. Могу:\n\n"
                "- **обстановка и прогноз**: «какая обстановка», «какой пик уровня»\n"
                "- **дамбы**: «какая дамба самая опасная»\n"
                "- **SOS и бригады**: «кого спасать первым»\n"
                "- **сценарии**: «что будет, если сброс увеличат на 80 м³/с» или «потепление на 5 градусов»\n"
                "- **оповещения**: «подготовь оповещение для Подгоры»\n"
                "- **сводка для акима**: «дай сводку»")
    if kind in ("brief", "level", "dams", "rain") and not st:
        return "Нет доступа к обстановке для вашей роли."
    if kind == "brief":
        p = st["forecast_p50"]; peak = max(p); day = p.index(peak) + 1
        segs = sorted(st["segments"], key=lambda s: -s["risk"])
        w = segs[0]
        rain = max([r["rain_max_3h_mm_h"] for r in st["rain"].values()] or [0])
        lines = [f"**Сводка на сейчас**",
                 f"1. Уровень Есиля **{st['level_now_m']:.2f} м**, за сутки {st['rise_m_per_day']:+.2f} м; опасная отметка {st['danger_level_m']:.2f} м.",
                 f"2. Прогноз: пик около **{peak:.2f} м** на {day}-й день (P90 до {max(st['forecast_p90']):.2f} м)"
                 + (", это **выше опасной отметки**." if peak >= st["danger_level_m"] else "."),
                 f"3. Самый опасный участок: **{w['name']}**, риск {w['risk']:.0%}; причина: {DRIVER.get(w['main_driver'], w['main_driver'])}.",
                 f"4. Ливень по радиолиниям: до {rain:.0f} мм/ч за 3 ч; вода в снеге {st['snow_swe_mm']:.0f} мм.",
                 f"5. Активных тревог: {len(st['alerts'])}" + (f" ({'; '.join(a['title'] for a in st['alerts'])})." if st["alerts"] else ".")]
        return "\n".join(lines)
    if kind == "level":
        p, p90 = st["forecast_p50"], st["forecast_p90"]
        rows = "\n".join(f"| +{d} д | {p[d-1]:.2f} | {p90[d-1]:.2f} |" for d in (1, 3, 5, 7, 10, 15) if d <= len(p))
        ext = st.get("external_forecast")
        tail = ""
        if ext and ext.get("p50"):
            tail = f"\n\nДля сравнения, {ext.get('source', 'внешний')} даёт пик {max(ext['p50']):.2f} м."
        return (f"Сейчас **{st['level_now_m']:.2f} м** ({st['rise_m_per_day']:+.2f} м/сут). Прогноз ARLAN:\n\n"
                f"| День | P50, м | P90, м |\n|---|---|---|\n{rows}{tail}")
    if kind == "dams":
        segs = sorted(st["segments"], key=lambda s: -s["risk"])
        rows = "\n".join(f"| {s['name']} | {s['risk']:.0%} ({s['level_ru']}) | {s['freeboard_forecast_m']:.2f} | {DRIVER.get(s['main_driver'], s['main_driver'])} |" for s in segs)
        w = segs[0]
        return (f"Самый опасный участок: **{w['name']}**, риск {w['risk']:.0%}. "
                f"Запас до гребня по пессимистичному прогнозу {w['freeboard_forecast_m']:.2f} м; главная причина: {DRIVER.get(w['main_driver'])}.\n\n"
                f"| Участок | Риск | Запас P90, м | Причина |\n|---|---|---|---|\n{rows}\n\n"
                "Рекомендую усилить обход на первых двух участках. Решение принимает штаб. Отметки дамб в демо условные.")
    if kind == "rain":
        rows = "\n".join(f"| {k} | {v['rain_mm_h']:.1f} | {v['rain_max_3h_mm_h']:.1f} |" for k, v in st["rain"].items())
        return "Ливень по радиолиниям сотовых операторов:\n\n| Линия | Сейчас, мм/ч | Макс. 3 ч, мм/ч |\n|---|---|---|\n" + (rows or "| — | — | — |")
    if kind == "sos":
        q = (res.get("list_sos") or {}).get("sos", [])
        if not q:
            return "Активных SOS нет."
        top = q[:5]
        rows = "\n".join(f"| №{s['id']} | {s['priority']} | {s.get('address') or ''} | {s['people']} (дети {s['children']}, пожилые {s['elderly']}) | {WATER.get(s['water'], s['water'])} | {s['status']} |" for s in top)
        first = next((s for s in q if s["status"] == "new"), None)
        rec = ""
        if first:
            r = run_tool("recommend_units", {"sos_id": first["id"]}, user)
            c = r.get("candidates", [])
            if c:
                rec = (f"\n\n**Первым:** вызов №{first['id']} ({first['priority_reason']}). "
                       f"Лучше всего отправить **{c[0]['callsign']}**: {c[0]['why']}."
                       + (f" Запасной вариант: {c[1]['callsign']} ({c[1]['why']})." if len(c) > 1 else "")
                       + (" Назначить можно в диспетчерской или написать: «назначь " + c[0]["callsign"] + f" на {first['id']}»." if has(user, "sos.dispatch") else ""))
        return (f"В очереди {len(q)} активных вызовов, ждут {sum(s['people'] for s in q)} человек. По срочности:\n\n"
                f"| Вызов | Приоритет | Адрес | Люди | Вода | Статус |\n|---|---|---|---|---|---|\n{rows}{rec}")
    if kind == "units":
        u = (res.get("list_units") or {}).get("units", [])
        free = [x for x in u if x["status"] == "available"]
        rows = "\n".join(f"| {x['callsign']} | {x['kind']} | {x['service']} | {'свободна' if x['status'] == 'available' else 'на вызове'} |" for x in u)
        return f"Свободно {len(free)} из {len(u)} бригад.\n\n| Бригада | Тип | Служба | Статус |\n|---|---|---|---|\n{rows}"
    if kind == "incidents":
        inc = (res.get("list_incidents") or {}).get("incidents", [])
        if not inc:
            return "Открытых инцидентов нет."
        return "Открытые инциденты:\n\n" + "\n".join(f"- **№{i['id']}** {i['title']} ({i['severity']}, {i['status']})" for i in inc[:10])
    if kind == "incident_create":
        seg = _segment(text.lower())
        s = next((x for x in st.get("segments", []) if x["segment_id"] == seg), None) if seg else None
        title = (f"{s['name']}: риск {s['level_ru']}" if s else text[:120])
        r = run_tool("create_incident", {"title": title, "kind": "dam" if s else "flood", "severity": (s or {}).get("level", "medium") if s else "medium",
                                         "segment_id": seg, "note": "Создан ассистентом по запросу"}, user)
        return f"Создал инцидент **№{r.get('incident_id')}**: {title}. Он в разделе «Инциденты»." if r.get("ok") else r.get("error", "Не получилось.")
    if kind == "scenario":
        sc = res.get("run_scenario") or {}
        if "error" in sc:
            return sc["error"]
        base_peak = max(st["forecast_p50"]) if st else None
        prm = sc.get("params", {})
        desc = []
        if prm.get("release_extra_m3s"):
            desc.append(f"доп. сброс {prm['release_extra_m3s']:.0f} м³/с")
        if prm.get("temp_delta_c"):
            desc.append(f"температура {prm['temp_delta_c']:+.0f} °C")
        if prm.get("snow_multiplier"):
            desc.append(f"снегозапас ×{prm['snow_multiplier']:.1f}")
        if prm.get("breach_segment"):
            desc.append(f"прорыв участка {prm['breach_segment']}")
        if not desc:
            return "Не понял параметры сценария. Пример: «что будет, если сброс увеличат на 80 м³/с и потеплеет на 5 градусов»."
        rows = "\n".join(f"| {s['name']} | {s['risk']:.0%} ({s['level_ru']}) | {s['freeboard_forecast_m']:.2f} |" for s in sorted(sc["segments"], key=lambda s: -s["risk"]))
        delta = f" (сейчас без изменений {base_peak:.2f} м, разница {sc['peak_m'] - base_peak:+.2f} м)" if base_peak else ""
        over = "выше" if sc["peak_m"] >= sc["danger_level_m"] else "ниже"
        return (f"Сценарий: {', '.join(desc)}.\n\nПик **{sc['peak_m']:.2f} м** на {sc['peak_day']}-й день{delta}; это {over} опасной отметки {sc['danger_level_m']:.2f} м. "
                f"P90 до {sc['p90_max_m']:.2f} м.\n\n| Участок | Риск | Запас P90, м |\n|---|---|---|\n{rows}\n\n"
                "Карту затопления на пик можно посмотреть в разделе «Сценарии».")
    if kind == "alert":
        ds = _district(text.lower()) or [next((s["district"] for s in sorted(st.get("segments", []), key=lambda s: -s["risk"])), "podgora")]
        peak = max(st["forecast_p50"]) if st else None
        names = ", ".join(DIST_RU[d] for d in ds)
        ru = (f"Жители: {names}! По прогнозу ARLAN уровень Есиля поднимется до {peak:.1f} м"
              + (" — выше опасной отметки." if st and peak >= st["danger_level_m"] else ".")
              + " Подготовьте документы, лекарства, воду и зарядку для телефона. Следите за сообщениями ДЧС. Если нужна помощь: 112 или кнопка SOS на сайте.")
        kk = (f"{names} тұрғындары! ARLAN болжамы бойынша Есіл деңгейі {peak:.1f} м-ге дейін көтеріледі. "
              "Құжаттарды, дәрі-дәрмекті, суды және телефон қуаттағышын дайындаңыздар. ТЖД хабарламаларын қадағалаңыздар. Көмек керек болса: 112.")
        if has(user, "alert.prepare"):
            r = run_tool("draft_alert", {"title": f"Угроза подтопления: {names}", "text_ru": ru, "text_kk": kk, "districts": ds}, user)
            head = f"Подготовил оповещение №{r.get('notification_id')} и отправил руководителю на утверждение (раздел «Оповещения»).\n\n"
        else:
            head = "Вот текст. Отправить на утверждение может дежурный или руководитель.\n\n"
        return head + f"**RU:** {ru}\n\n**KZ:** {kk}\n\n_Казахский текст стоит проверить носителю языка._"
    if kind == "assign":
        u = (res.get("list_units") or {}).get("units", [])
        unit = next((x for x in u if x["callsign"].lower() in text.lower()), None)
        rest = text.lower().replace(unit["callsign"].lower(), " ") if unit else text
        m = re.search(r"(\d+)", rest)
        if not m or not unit:
            return "Укажите бригаду и номер вызова, например: «назначь Лодка-2 на 3»."
        r = run_tool("assign_unit", {"sos_id": int(m.group(1)), "unit_id": unit["id"]}, user)
        return f"Назначил **{unit['callsign']}**. Статус вызова: {r['sos']['status']}." if r.get("ok") else r.get("error", "Не получилось.")
    return "Не понял запрос. Напишите «что умеешь», и я покажу примеры."


def local_reply(conv_id: int, user: dict, text: str):
    from .assistant import _sse, run_tool
    tools, kind = plan(text, user)
    res, notes = {}, []
    for name, args in tools:
        yield _sse({"type": "tool", "name": name, "input": args})
        out = run_tool(name, args, user)
        res[name] = out
        notes.append({"type": "tool_note", "name": name})
        yield _sse({"type": "tool_result", "name": name, "ok": "error" not in out})
    try:
        answer = compose(kind, text, res, user, run_tool)
    except Exception as e:  # noqa: BLE001
        answer = f"Не получилось собрать ответ ({e}). Попробуйте переформулировать."
    for chunk in re.findall(r"\S+\s*", answer):
        yield _sse({"type": "text", "delta": chunk})
        time.sleep(0.012)
    content = notes + [{"type": "text", "text": answer}]
    db.insert_row(db.messages, conversation_id=conv_id, ts=db.now(), role="assistant", content=json.dumps(content, ensure_ascii=False))
    db.update_row(db.conversations, db.conversations.c.id, conv_id, updated_at=db.now())
    yield _sse({"type": "done"})
