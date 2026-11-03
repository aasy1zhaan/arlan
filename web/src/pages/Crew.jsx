import { useEffect, useRef, useState } from "react";
import MapView from "../MapView.jsx";
import { api, fmt, KIND, STATUS, WATER } from "../api.js";
import { buildRoute, splitByFlood } from "../routing.js";
import { useCityState } from "./Situation.jsx";

export default function Crew({ user }) {
  const [state] = useCityState();
  const [d, setD] = useState(null);
  const [route, setRoute] = useState(null);
  const [gps, setGps] = useState(false);
  const [rescued, setRescued] = useState(0);
  const [msg, setMsg] = useState("");
  const terrain = useRef(null);
  const watch = useRef(null);

  const load = () => api("/api/v1/my-task").then(setD).catch((e) => setMsg(e.message));
  useEffect(() => { load(); const t = setInterval(load, 10000); return () => clearInterval(t); }, []);
  useEffect(() => () => watch.current != null && navigator.geolocation.clearWatch(watch.current), []);

  useEffect(() => {
    (async () => {
      if (!d?.task || !d.unit) { setRoute(null); return; }
      const r = await buildRoute([d.unit.lon, d.unit.lat], [d.task.lon, d.task.lat], d.unit.kind);
      const t = terrain.current;
      const parts = r.water ? { dry: [r.coords], wet: [] } : splitByFlood(r.coords, t?.elev, t && state ? t.riverBase + state.level.now_m : null);
      const lo = r.coords.map((c) => c[0]), la = r.coords.map((c) => c[1]);
      setRoute({ ...parts, bounds: [[Math.min(...lo), Math.min(...la)], [Math.max(...lo), Math.max(...la)]] });
    })();
  }, [d?.task?.id, d?.unit?.lat]);

  function toggleGps() {
    if (gps) { navigator.geolocation.clearWatch(watch.current); watch.current = null; setGps(false); return; }
    if (!navigator.geolocation) { setMsg("Нет геолокации на устройстве"); return; }
    watch.current = navigator.geolocation.watchPosition(
      (p) => api(`/api/v1/units/${user.unit_id}/position`, { method: "POST", body: { lat: p.coords.latitude, lon: p.coords.longitude } }).catch(() => {}),
      () => setMsg("Нет доступа к геолокации"), { enableHighAccuracy: true });
    setGps(true);
  }
  async function status(st) {
    try { await api(`/api/v1/sos/${d.task.id}/status`, { method: "POST", body: { status: st, rescued: st === "resolved" ? rescued : undefined } }); setMsg(STATUS[st]); load(); }
    catch (e) { setMsg(e.message); }
  }

  const t = d?.task;
  return (
    <div className="crew">
      <section className="crew-map">
        <MapView state={state} waterLevel={state?.level.now_m} sos={t ? [t] : []} units={d?.unit ? [d.unit] : []} route={route} spin={false}
          onReady={(x) => (terrain.current = x)} initial={{ center: [69.11, 54.886], zoom: 13.4, pitch: 45, bearing: 0 }} />
      </section>
      <section className="crew-panel glass">
        <div className="card-h"><span>{d?.unit ? `${d.unit.callsign} · ${KIND[d.unit.kind]}` : "Бригада"}</span>
          <button className={"chip" + (gps ? " on" : "")} onClick={toggleGps}>{gps ? "GPS передаётся" : "Включить GPS"}</button></div>
        {!t && <p className="muted">Активной задачи нет. Ожидайте назначения диспетчером.</p>}
        {t && <>
          <h2>{t.address || `Вызов №${t.id}`}</h2>
          <p className="muted">{t.priority_reason}</p>
          <div className="facts">
            <div><small>Людей</small><b>{t.people}</b></div><div><small>Дети</small><b>{t.children}</b></div>
            <div><small>Пожилые</small><b>{t.elderly}</b></div><div><small>Вода</small><b>{WATER[t.water]}</b></div>
          </div>
          {t.comment && <p className="quote">«{t.comment}»</p>}
          <p>Телефон: <a href={"tel:" + t.phone}>{t.phone}</a> · {fmt(t.lat, 5)}, {fmt(t.lon, 5)}</p>
          <a className="btn-ghost" href={`https://www.google.com/maps/dir/?api=1&destination=${t.lat},${t.lon}`} target="_blank" rel="noreferrer">Открыть в навигаторе</a>
          <div className="row-btns">
            {t.status === "assigned" && <button className="btn-lime" onClick={() => status("en_route")}>Выехали</button>}
            {["assigned", "en_route"].includes(t.status) && <button className="btn-ghost" onClick={() => status("on_scene")}>На месте</button>}
          </div>
          {t.status === "on_scene" && <div className="resc">
            <label htmlFor="resc">Эвакуировано человек</label>
            <input id="resc" type="number" min="0" value={rescued} onChange={(e) => setRescued(+e.target.value)} />
            <button className="btn-lime" onClick={() => status("resolved")}>Завершить вызов</button>
          </div>}
        </>}
        {msg && <p className="muted">{msg}</p>}
      </section>
    </div>
  );
}
