import { useEffect, useMemo, useRef, useState } from "react";
import MapView from "../MapView.jsx";
import { ago, api, can, fmt, KIND, SERVICE, STATUS, WATER } from "../api.js";
import { buildRoute, splitByFlood } from "../routing.js";
import { useCityState } from "./Situation.jsx";
import Icon from "../Icon.jsx";

const prio = (p) => (p >= 80 ? "p-crit" : p >= 60 ? "p-high" : p >= 40 ? "p-med" : "p-low");

export default function Dispatch({ user }) {
  const [state] = useCityState();
  const [sos, setSos] = useState([]);
  const [units, setUnits] = useState([]);
  const [sel, setSel] = useState(null);
  const [route, setRoute] = useState(null);
  const [routeInfo, setRouteInfo] = useState(null);
  const [filter, setFilter] = useState("open");
  const [err, setErr] = useState("");
  const [toast, setToast] = useState("");
  const terrain = useRef(null);

  const load = () => Promise.all([api("/api/v1/sos?status=" + filter), api("/api/v1/units")])
    .then(([s, u]) => { setSos(s); setUnits(u); setErr(""); }).catch((e) => setErr(e.message));
  useEffect(() => { load(); const t = setInterval(load, 10000); return () => clearInterval(t); }, [filter]);
  useEffect(() => { if (toast) { const t = setTimeout(() => setToast(""), 2800); return () => clearTimeout(t); } }, [toast]);

  const cur = sos.find((s) => s.id === sel);
  const curUnit = cur && units.find((u) => u.id === cur.unit_id);

  async function showRoute(unit, s) {
    if (!unit || !s || unit.lat == null) { setRoute(null); setRouteInfo(null); return; }
    const r = await buildRoute([unit.lon, unit.lat], [s.lon, s.lat], unit.kind);
    const t = terrain.current;
    const flood = t && state ? t.riverBase + state.level.now_m : null;
    const parts = r.water ? { dry: [], wet: [] } : splitByFlood(r.coords, t?.elev, flood);
    if (r.water) parts.dry = [r.coords];
    const lons = r.coords.map((c) => c[0]), lats = r.coords.map((c) => c[1]);
    setRoute({ ...parts, bounds: [[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]] });
    const wetKm = parts.wet.reduce((a, seg) => a + seg.reduce((b, p, i) => (i ? b + Math.hypot((p[0] - seg[i - 1][0]) * 64, (p[1] - seg[i - 1][1]) * 111) : b), 0), 0);
    setRouteInfo({ unit: unit.callsign, source: r.source, km: r.km, min: r.min, wetKm, water: r.water });
  }

  useEffect(() => { if (cur) showRoute(curUnit || (cur.recommended && units.find((u) => u.id === cur.recommended[0]?.id)), cur); else { setRoute(null); setRouteInfo(null); } }, [sel, units.length, cur?.unit_id]);

  async function assign(uid) {
    try { await api(`/api/v1/sos/${cur.id}/assign`, { method: "POST", body: { unit_id: uid } }); setToast("Бригада назначена"); load(); }
    catch (e) { setToast(e.message); }
  }
  async function status(st) {
    try { await api(`/api/v1/sos/${cur.id}/status`, { method: "POST", body: { status: st } }); setToast(STATUS[st]); load(); }
    catch (e) { setToast(e.message); }
  }

  const stats = useMemo(() => ({
    fresh: sos.filter((s) => s.status === "new").length,
    people: sos.reduce((a, s) => a + (s.people || 0), 0),
    free: units.filter((u) => u.status === "available").length,
  }), [sos, units]);

  return (
    <div className="dispatch">
      <section className="disp-map">
        <MapView state={state} waterLevel={state?.level.now_m} sos={sos} units={units} route={route} selectedSos={sel} onSos={setSel}
          shelters={[]} spin={false} onReady={(t) => (terrain.current = t)} initial={{ center: [69.11, 54.886], zoom: 13.2, pitch: 52, bearing: -18 }} />
        <div className="disp-head glass">
          <div><b>{stats.fresh}</b><small>новых SOS</small></div>
          <div><b>{stats.people}</b><small>человек ждут</small></div>
          <div><b>{stats.free}</b><small>свободных бригад</small></div>
          <div className="muted disp-svc">{user.service_title || "Все службы"}</div>
        </div>
        {routeInfo && (
          <div className="route-card glass">
            <div className="card-h"><span><Icon name="route" /> Маршрут: {routeInfo.unit}</span></div>
            <p className="muted">{routeInfo.source}{routeInfo.km ? ` · ${fmt(routeInfo.km, 1)} км · ~${Math.round(routeInfo.min)} мин` : ""}</p>
            {!routeInfo.water && routeInfo.wetKm > 0.05 && <p className="warn">Около {fmt(routeInfo.wetKm, 1)} км дороги под водой (красный пунктир). Нужна лодка или объезд.</p>}
            {!routeInfo.water && routeInfo.wetKm <= 0.05 && <p className="ok">По текущему уровню дорога сухая.</p>}
            {routeInfo.water && <p className="muted">Лодка идёт напрямую по воде.</p>}
          </div>
        )}
      </section>

      <section className="disp-side">
        <div className="disp-tabs">
          {[["open", "Активные"], ["resolved", "Завершённые"], ["all", "Все"]].map(([k, t]) => <button key={k} className={"chip" + (filter === k ? " on" : "")} onClick={() => setFilter(k)}>{t}</button>)}
        </div>
        {err && <div className="err">{err}</div>}
        {!cur && (
          <div className="sos-list">
            {sos.length === 0 && <div className="muted">Вызовов нет.</div>}
            {sos.map((s) => (
              <button key={s.id} className="sos-item" onClick={() => setSel(s.id)}>
                <span className={"prio " + prio(s.priority)}>{s.priority}</span>
                <span className="sos-main">
                  <b>{s.address || `${fmt(s.lat, 4)}, ${fmt(s.lon, 4)}`}</b>
                  <small>{s.priority_reason}</small>
                  <span className="sos-tags">
                    <em>{STATUS[s.status]}</em>{s.services.map((x) => <em key={x}>{SERVICE[x]}</em>)}<em>{ago(s.created_at)}</em>
                  </span>
                </span>
              </button>
            ))}
          </div>
        )}
        {cur && (
          <div className="sos-detail">
            <button className="back" onClick={() => setSel(null)}>← Все вызовы</button>
            <div className="sos-title"><span className={"prio big " + prio(cur.priority)}>{cur.priority}</span><div><h2>{cur.address || "Вызов №" + cur.id}</h2><small className="muted">№{cur.id} · {ago(cur.created_at)} · {STATUS[cur.status]}</small></div></div>
            <div className="facts">
              <div><small>Людей</small><b>{cur.people}</b></div>
              <div><small>Дети</small><b>{cur.children}</b></div>
              <div><small>Пожилые</small><b>{cur.elderly}</b></div>
              <div><small>Вода</small><b>{WATER[cur.water]}</b></div>
            </div>
            <div className="sos-tags">
              {cur.immobile && <em className="hot">лежачий</em>}{cur.medical && <em className="hot">медпомощь{cur.medical_note ? ": " + cur.medical_note : ""}</em>}
              {cur.crime && <em className="hot">угроза безопасности</em>}{cur.services.map((x) => <em key={x}>{SERVICE[x]}</em>)}
            </div>
            {cur.comment && <p className="quote">«{cur.comment}»</p>}
            {cur.photo && <img className="sos-photo" src={cur.photo} alt="Фото от жителя" />}
            <p className="muted">Телефон: {cur.phone} · {fmt(cur.lat, 5)}, {fmt(cur.lon, 5)}</p>

            {cur.status === "new" && can(user, "sos.dispatch") && (
              <>
                <h4>Рекомендованные бригады</h4>
                {(cur.recommended || []).length === 0 && <p className="muted">Свободных бригад нужной службы нет.</p>}
                {(cur.recommended || []).map((u, i) => (
                  <div key={u.id} className={"unit-rec" + (i === 0 ? " best" : "")}>
                    <div><b>{u.callsign}</b><small>{KIND[u.kind]} · {u.why}</small></div>
                    <button className="btn-ghost" onClick={() => showRoute(units.find((x) => x.id === u.id), cur)}>Маршрут</button>
                    <button className="btn-lime" onClick={() => assign(u.id)}>Назначить</button>
                  </div>
                ))}
              </>
            )}
            {cur.status !== "new" && curUnit && (
              <div className="unit-rec best"><div><b>{curUnit.callsign}</b><small>{KIND[curUnit.kind]} · {SERVICE[curUnit.service]}</small></div></div>
            )}
            {can(user, "sos.dispatch") && cur.status !== "new" && cur.status !== "resolved" && (
              <div className="row-btns">
                {cur.status === "assigned" && <button className="btn-ghost" onClick={() => status("en_route")}>В пути</button>}
                {["assigned", "en_route"].includes(cur.status) && <button className="btn-ghost" onClick={() => status("on_scene")}>На месте</button>}
                <button className="btn-lime" onClick={() => status("resolved")}>Завершить</button>
                <button className="btn-ghost" onClick={() => status("new")}>Снять бригаду</button>
              </div>
            )}
          </div>
        )}
        <h4 className="units-h">Бригады</h4>
        <div className="units">
          {units.map((u) => <div key={u.id} className={"unit-row " + u.status}><i /><b>{u.callsign}</b><small>{KIND[u.kind]} · {SERVICE[u.service]}</small><em>{u.status === "available" ? "свободна" : u.status === "busy" ? "на вызове" : "не в сети"}</em></div>)}
        </div>
      </section>
      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}
