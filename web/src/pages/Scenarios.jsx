import { useEffect, useState } from "react";
import MapView from "../MapView.jsx";
import LevelChart from "../LevelChart.jsx";
import { api, fmt, SEV } from "../api.js";
import { useCityState } from "./Situation.jsx";

const SEGS = { "": "Без прорыва", PODG: "Дамба ул. Ущева", KOZH: "Кожевенный", RECH: "Вал объездной", ZAR: "Заречный" };

export default function Scenarios() {
  const [base] = useCityState();
  const [p, setP] = useState({ temp_delta_c: 0, release_extra_m3s: 0, snow_multiplier: 1, breach_segment: "" });
  const [res, setRes] = useState(null);
  const [saved, setSaved] = useState([]);
  const [name, setName] = useState("");
  const [err, setErr] = useState("");
  const loadSaved = () => api("/api/v1/scenarios").then(setSaved).catch(() => {});
  useEffect(() => { loadSaved(); }, []);

  async function run(save = false) {
    setErr("");
    try {
      const r = await api("/api/v1/scenarios/run", { method: "POST", body: { ...p, breach_segment: p.breach_segment || null, save, name: name || "Сценарий" } });
      setRes(r); if (save) loadSaved();
    } catch (e) { setErr(e.message); }
  }
  useEffect(() => { if (base) run(); }, [base?.generated_at]);

  const view = res && base ? { ...base, forecast: res.forecast, segments: res.segments } : base;
  const peak = res ? Math.max(...res.forecast.p50) : null;
  return (
    <div className="scen">
      <section className="scen-map">
        {view && <MapView state={view} waterLevel={peak ?? view.level.now_m} spin={false} initial={{ center: [69.1, 54.888], zoom: 12.8, pitch: 60, bearing: -24 }} />}
        {peak != null && <div className="scen-peak glass"><small>Пик по сценарию</small><b>{fmt(peak)} м</b><small>{peak >= base.level.danger_m ? "выше опасной отметки" : "ниже опасной отметки"} · затопление на карте показано на пик</small></div>}
      </section>
      <section className="scen-panel">
        <h1>Сценарии «что если»</h1>
        <div className="glass form">
          <label>Температура: {p.temp_delta_c > 0 ? "+" : ""}{p.temp_delta_c} °C к прогнозу<input type="range" min="-8" max="10" step="1" value={p.temp_delta_c} onChange={(e) => setP({ ...p, temp_delta_c: +e.target.value })} /></label>
          <label>Доп. сброс из Сергеевского вдхр: {p.release_extra_m3s} м³/с<input type="range" min="0" max="200" step="10" value={p.release_extra_m3s} onChange={(e) => setP({ ...p, release_extra_m3s: +e.target.value })} /></label>
          <label>Снегозапас: ×{p.snow_multiplier.toFixed(1)}<input type="range" min="0.5" max="2" step="0.1" value={p.snow_multiplier} onChange={(e) => setP({ ...p, snow_multiplier: +e.target.value })} /></label>
          <label>Прорыв дамбы<select value={p.breach_segment} onChange={(e) => setP({ ...p, breach_segment: e.target.value })}>{Object.entries(SEGS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
          <div className="row-btns"><button className="btn-lime" onClick={() => run()}>Рассчитать</button><input placeholder="Название" value={name} onChange={(e) => setName(e.target.value)} aria-label="Название сценария" /><button className="btn-ghost" onClick={() => run(true)}>Сохранить</button></div>
          {err && <div className="err">{err}</div>}
        </div>
        {res && base && <div className="glass card-level"><div className="card-h"><span>Прогноз: сценарий (салатовый) против базового (пунктир)</span></div><LevelChart state={{ ...base, forecast: res.forecast }} compare={base.forecast} /></div>}
        {res && <table className="tbl"><thead><tr><th>Участок</th><th>Риск</th><th>Запас P90, м</th></tr></thead><tbody>
          {[...res.segments].sort((a, b) => b.risk - a.risk).map((s) => <tr key={s.segment_id}><td>{s.name}</td><td><span className="pill" style={{ background: SEV[s.level] }}>{Math.round(s.risk * 100)}%</span></td><td>{fmt(s.freeboard_forecast_m)}</td></tr>)}
        </tbody></table>}
        {saved.length > 0 && <><h4>Сохранённые</h4>{saved.map((s) => <div key={s.id} className="row"><span>{s.name}</span><span className="muted">пик {fmt(s.peak_m)} м</span></div>)}</>}
      </section>
    </div>
  );
}
