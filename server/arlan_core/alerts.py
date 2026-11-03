"""Alert rules + delivery (Telegram). Deduplicated with a cooldown per alert key."""
from __future__ import annotations

import os
import time

COOLDOWN_S = 6 * 3600


class AlertEngine:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.districts = {d["id"]: d for d in cfg["districts"]}
        self.last_sent: dict[str, float] = {}
        self.history: list[dict] = []

    def evaluate(self, st: dict) -> list[dict]:
        active = []
        for s in st["segments"]:
            if s["level"] in ("high", "critical"):
                d = self.districts.get(s["district"], {})
                active.append({
                    "key": f"seg:{s['segment_id']}:{s['level']}",
                    "severity": s["level"],
                    "district": s["district"],
                    "title": f"{s['name']}: риск {s['level_ru']}",
                    "text": (f"Запас до гребня по прогнозу P90: {s['freeboard_forecast_m']} м. "
                             f"Главный фактор: {FACTOR_RU.get(s['main_driver'], s['main_driver'])}. "
                             f"Жителям района {d.get('name', '')}: подготовить документы и вещи, "
                             f"следить за сообщениями ДЧС."),
                })
        thr = self.cfg.get("rain_alert_mm_h", 15)
        for lid, r in st.get("rain", {}).items():
            if r["rain_max_3h_mm_h"] >= thr:
                link = next((l for l in self.cfg["cml_links"] if l["id"] == lid), None)
                for dist in (link or {}).get("districts", []):
                    active.append({
                        "key": f"rain:{dist}",
                        "severity": "high" if r["rain_max_3h_mm_h"] >= 2 * thr else "medium",
                        "district": dist,
                        "title": f"Сильный ливень: {self.districts.get(dist, {}).get('name', dist)}",
                        "text": f"Интенсивность до {r['rain_max_3h_mm_h']} мм/ч. Возможны подтопления улиц и подвалов.",
                    })
        now = time.time()
        for a in active:
            if now - self.last_sent.get(a["key"], 0) > COOLDOWN_S:
                self.last_sent[a["key"]] = now
                a["sent_at"] = now
                self.history.append(a)
                self._deliver(a)
        return active

    def _deliver(self, a: dict):
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        chat = self.districts.get(a["district"], {}).get("telegram_chat") or os.environ.get("TELEGRAM_DEFAULT_CHAT")
        if not (token and chat):
            return
        try:
            import requests
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat, "text": f"ARLAN | {a['title']}\n{a['text']}"},
                          timeout=10)
        except Exception:  # noqa: BLE001 - alerts must never crash the API
            pass


FACTOR_RU = {
    "freeboard": "малый запас до гребня",
    "rise": "быстрый подъём воды",
    "das": "аномалия в оптоволокне (возможна фильтрация)",
    "piezo": "высокий уровень воды внутри дамбы",
    "age": "возраст сооружения",
}
