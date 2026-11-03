import { useEffect, useMemo, useState } from "react";
import MapView from "../MapView.jsx";
import { api, can, fmt, SEV } from "../api.js";
import { SEGMENTS } from "../geo.js";
import LevelChart from "../LevelChart.jsx";

const DRIVER = { freeboard: "Малый запас до гребня", rise: "Быстрый подъём воды", das: "Аномалия в оптоволокне", piezo: "Вода внутри дамбы", age: "Возраст сооружения" };

function Ring({ value, color }) {
  const r = 34, c = 2 * Math.PI * r;
  return (
    <svg viewBox="0 0 84 84" className="ring" aria-hidden="true">
      <circle cx="42" cy="42" r={r} stroke="rgba(255,255,255,0.10)" strokeWidth="6" fill="none" strokeDasharray="2 4" />
      <circle cx="42" cy="42" r={r} stroke={color} strokeWidth="6" fill="none" strokeLinecap="round" strokeDasharray={`${c * value} ${c}`} transform="rotate(-90 42 42)" />
    </svg>
  );
}

export function useCityState(ms = 60000) {
  const [state, setState] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    let live = true;
    const load = () => api("/api/v1/state").then((s) => live && (setState(s), setErr(""))).catch((e) => live && setErr(e.message));
    load();
    const t = setInterval(load, ms);
    return () => { live = false; clearInterval(t); };
  }, [ms]);
  return [state, err];
}

export default function Situation({ user }) {
  const [state, err] = useCityState();
  const [day, setDay] = useState(0);
  const [sel, setSel] = useState(null);
  const [lang, setLang] = useState("ru");
  const [toast, setToast] = useState("");
  const [shelters, setShelters] = useState([]);
  useEffect(() => { api("/api/v1/config").then((c) => setShelters(c.shelters || [])).catch(() => {}); }, []);
  useEffect(() => { if (toast) { const t = setTimeout(() => setToast(""), 2600); return () => clearTimeout(t); } }, [toast]);
  const segs = useMemo(() => (state ? [...state.segments].sort((a, b) => b.risk - a.risk) : []), [state]);

  if (!state) return <div className="page-pad">{err ? <div className="err">{err}</div> : <div className="muted">Загружаем обстановку…</div>}</div>;
  const fc = state.forecast;
  const level = day === 0 ? state.level.now_m : fc.p50[day - 1];
  const peak = Math.max(...fc.p50), peakDay = fc.p50.indexOf(peak) + 1;
  const threat = Math.max(...segs.map((s) => s.risk));
  const counts = ["low", "medium", "high"].map((l) => segs.filter((s) => s.level === l || (l === "high" && s.level === "critical")).length);
  const rain = Object.entries(state.rain || {});
  const rainMax = Math.max(0, ...rain.map(([, r]) => r.rain_max_3h_mm_h));

  async function createIncident(s) {
    try {
      await api("/api/v1/incidents", { method: "POST", body: { title: `${s.name}: риск ${s.level_ru}`, kind: "dam", severity: s.level, segment_id: s.segment_id, district: s.district, note: `Создан с карты. Причина: ${DRIVER[s.main_driver]}` } });
      setToast("Инцидент создан");
    } catch (e) { setToast(e.message); }
  }

  return (
    <div className="situation">
      <section className="stage">
        <MapView state={state} waterLevel={level} selected={sel} onSelect={setSel} shelters={shelters} />
        <div className="vignette" />
        <header className="top">
          <div className="pillbar">
            <span>Петропавловск · р. Есиль</span><span className="sep" />
            <span className="muted">обновлено {new Date(state.generated_at).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}</span>
          </div>
          <div className="top-r">
            <div className="seg2">
              <button aria-pressed={lang === "ru"} onClick={() => setLang("ru")}>RU</button>
              <button aria-pressed={lang === "kk"} onClick={() => setLang("kk")}>KZ</button>
            </div>
          </div>
        </header>

        <div className="hero">
          <h1>Город,<br />который<br />слышит воду <span className="ai">AI · 4 сенсора</span></h1>
          {state.alerts.length > 0 && <button className="alertpill" onClick={() => setSel(segs[0].segment_id)}><i /> {state.alerts.length} тревоги · {state.alerts[0].title}</button>}
          <div className="glass card-level">
            <div className="card-h"><span>Уровень Есиля</span></div>
            <div className="lvl-nums">
              <div><b>{fmt(state.level.now_m)}</b><small>м сейчас</small></div>
              <div><b className="acc">{fmt(peak)}</b><small>пик · {peakDay}-й день</small></div>
              <div><b>{state.level.rise_m_per_day >= 0 ? "+" : ""}{fmt(state.level.rise_m_per_day)}</b><small>м / сутки</small></div>
            </div>
            <LevelChart state={state} day={day} />
          </div>
        </div>

        <aside className="right">
          <div className="glass card-threat">
            <div className="card-h"><span>Индекс угрозы ARLAN</span></div>
            <div className="threat-row">
              <div><b>{Math.round(threat * 100)}</b><sup>/100</sup><small>максимум по дамбам</small></div>
              <div><b>{fmt(rainMax, 0)}</b><sup>мм/ч</sup><small>ливень, 3 ч</small></div>
              <div><b>{fmt(state.snow.swe_mm, 0)}</b><sup>мм</sup><small>вода в снеге</small></div>
            </div>
            <div className="seg3"><span className="s-low">Норма · {counts[0]}</span><span className="s-med">Внимание · {counts[1]}</span><span className="s-high">Опасно · {counts[2]}</span></div>
          </div>
          <div className="pair">
            <div className="glass card-small">
              <div className="card-h"><span>Fiber Ear</span></div>
              <b className="big">{segs.reduce((a, s) => a + ((s.das && s.das.anomalous_channels) || []).length, 0)}<sup>кан.</sup></b>
              <small className="muted">аномалий в волокне из 1200</small>
              <div className="fiberbar">{segs.map((s) => <span key={s.segment_id} style={{ flex: 1, background: s.das?.anomalous_channels?.length ? "#FF4D5E" : "rgba(255,255,255,.18)" }} />)}</div>
            </div>
            <div className="glass card-small">
              <div className="card-h"><span>Rain Links</span></div>
              <b className="big">{rain.length}<sup>линий</sup></b>
              <small className="muted">сотовые радиолинии как дождемеры</small>
              <div className="bars">
                {rain.map(([k, r]) => <span key={k} title={`${k}: ${fmt(r.rain_max_3h_mm_h, 1)} мм/ч`} style={{ height: 6 + Math.min(40, r.rain_max_3h_mm_h * 1.2) }} className={r.rain_max_3h_mm_h > 15 ? "hot" : ""} />)}
                {(state.snow.stations || []).map((s) => <span key={s.station} className="snow" style={{ height: 6 + s.snow_depth_m * 60 }} title={`${s.station}: снег ${fmt(s.snow_depth_m * 100, 0)} см`} />)}
              </div>
            </div>
          </div>
          <div className="glass brief"><div className="card-h"><span>Сводка для ДЧС</span></div><p>{lang === "kk" ? state.briefing_kk : state.briefing_ru}</p></div>
        </aside>

        <div className="scrub glass">
          <span className="muted">Моделирование затопления</span>
          <input type="range" min="0" max={fc.p50.length} value={day} onChange={(e) => setDay(+e.target.value)} aria-label="День прогноза" />
          <span className="scrub-v"><b>{day === 0 ? "сейчас" : `+${day} д`}</b> · {fmt(level)} м</span>
        </div>
      </section>

      <section className="dock">
        <div className="dock-bar">
          <div className="chips">
            <button className={"chip" + (!sel ? " on" : "")} onClick={() => setSel(null)}>Все участки</button>
            {segs.map((s) => <button key={s.segment_id} className={"chip" + (sel === s.segment_id ? " on" : "")} onClick={() => setSel(s.segment_id)}>{SEGMENTS[s.segment_id]?.area || s.name}</button>)}
          </div>
        </div>
        <div className="cards">
          {segs.map((s) => {
            const g = SEGMENTS[s.segment_id] || { name: s.name, area: "" };
            const das = s.das?.anomalous_channels?.length;
            return (
              <article key={s.segment_id} className={"damcard" + (sel === s.segment_id ? " is-sel" : "")} onClick={() => setSel(s.segment_id)}>
                <header><span className="damcard-ic" style={{ background: SEV[s.level] }} /><div><h3>{g.name}</h3><p>{g.area} · {s.level_ru} риск</p></div></header>
                <div className="tags">
                  <span>запас {fmt(s.freeboard_now_m)} м</span><span>P90 {fmt(s.freeboard_forecast_m)} м</span>
                  <span className={das ? "tag-alert" : ""}>{das ? `волокно: ${das} кан.` : "волокно: тихо"}</span><span>{DRIVER[s.main_driver]}</span>
                </div>
                <div className="damcard-gauge">
                  {can(user, "incident.manage") && <div className="acts"><button title="Создать инцидент" onClick={(e) => { e.stopPropagation(); createIncident(s); }}>+</button></div>}
                  <div className="ringwrap"><Ring value={s.risk} color={SEV[s.level]} /><div className="ringval"><b>{Math.round(s.risk * 100)}<small>%</small></b><span>риск<br />прорыва</span></div></div>
                </div>
              </article>
            );
          })}
        </div>
        <footer className="foot">Данные датчиков в демо-конфигурации синтетические; линии дамб и отметки приблизительные, до получения данных акимата. Рельеф SRTM (Mapzen/AWS), спутник Esri.</footer>
      </section>
      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}
