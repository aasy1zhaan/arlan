import { useEffect, useState } from "react";
import { api, fmt, KIND, STATUS } from "../api.js";

const WATER_OPTS = [["none", "Воды нет"], ["ankle", "По щиколотку"], ["knee", "По колено"], ["waist", "По пояс"], ["chest", "По грудь"], ["roof", "Мы на крыше"]];

function Counter({ label, value, set, min = 0 }) {
  return (
    <div className="counter">
      <span>{label}</span>
      <div><button type="button" onClick={() => set(Math.max(min, value - 1))} aria-label={"Меньше: " + label}>−</button><b>{value}</b><button type="button" onClick={() => set(value + 1)} aria-label={"Больше: " + label}>+</button></div>
    </div>
  );
}

export default function SosPublic() {
  const [geo, setGeo] = useState(null);
  const [geoErr, setGeoErr] = useState("");
  const [f, setF] = useState({ phone: "", name: "", address: "", people: 1, children: 0, elderly: 0, immobile: false, medical: false, medical_note: "", water: "knee", crime: false, comment: "", photo: null });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const set = (k) => (v) => setF((x) => ({ ...x, [k]: v }));

  const locate = () => {
    if (!navigator.geolocation) { setGeoErr("Телефон не даёт геолокацию. Укажите адрес."); return; }
    setGeoErr("");
    navigator.geolocation.getCurrentPosition((p) => setGeo([p.coords.latitude, p.coords.longitude]),
      () => setGeoErr("Нет доступа к геолокации. Разрешите её или укажите адрес."), { enableHighAccuracy: true, timeout: 15000 });
  };
  useEffect(locate, []);

  function photo(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    const img = new Image();
    img.onload = () => {
      const c = document.createElement("canvas"); const s = Math.min(1, 900 / Math.max(img.width, img.height));
      c.width = img.width * s; c.height = img.height * s; c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
      set("photo")(c.toDataURL("image/jpeg", 0.7));
    };
    img.src = URL.createObjectURL(file);
  }

  async function submit(e) {
    e.preventDefault();
    if (!geo && !f.address) { setErr("Нужна геолокация или адрес"); return; }
    setBusy(true); setErr("");
    try {
      const [lat, lon] = geo || [54.8672, 69.1587];
      const r = await api("/api/v1/public/sos", { method: "POST", body: { ...f, lat, lon, comment: (f.comment || "") + (geo ? "" : " [без геолокации]") } });
      try { localStorage.setItem("arlan.sos", r.token); } catch { /* */ }
      location.hash = "#track/" + r.token;
    } catch (x) { setErr(x.message); } finally { setBusy(false); }
  }

  return (
    <div className="sos-page">
      <header className="sos-top"><img src="/logo.png" alt="ARLAN" /><a href="tel:112" className="call112">Позвонить 112</a></header>
      <form className="sos-form" onSubmit={submit}>
        <h1>Нужна помощь?</h1>
        <p className="muted">Вызов уйдёт в МЧС, скорую или полицию, в зависимости от ситуации. Если можете говорить, звоните 112.</p>
        <div className={"geo " + (geo ? "ok" : "")}>{geo ? `Геолокация: ${fmt(geo[0], 5)}, ${fmt(geo[1], 5)}` : geoErr || "Определяем ваше местоположение…"}{!geo && <button type="button" onClick={locate}>Повторить</button>}</div>
        <label>Адрес или ориентир<input value={f.address} onChange={(e) => set("address")(e.target.value)} placeholder="ул. Ущева 12, синий забор" /></label>
        <label>Телефон для связи *<input required type="tel" value={f.phone} onChange={(e) => set("phone")(e.target.value)} placeholder="+7 7__ ___ __ __" /></label>
        <fieldset><legend>Где вода?</legend><div className="opts">{WATER_OPTS.map(([k, t]) => <button type="button" key={k} className={f.water === k ? "on" : ""} onClick={() => set("water")(k)}>{t}</button>)}</div></fieldset>
        <div className="counters">
          <Counter label="Всего людей" value={f.people} set={set("people")} min={1} />
          <Counter label="Из них дети" value={f.children} set={set("children")} />
          <Counter label="Пожилые" value={f.elderly} set={set("elderly")} />
        </div>
        <div className="toggles">
          <button type="button" className={f.immobile ? "on" : ""} onClick={() => set("immobile")(!f.immobile)}>Есть лежачий / не может идти</button>
          <button type="button" className={f.medical ? "on" : ""} onClick={() => set("medical")(!f.medical)}>Нужна медпомощь</button>
          <button type="button" className={f.crime ? "on" : ""} onClick={() => set("crime")(!f.crime)}>Угроза безопасности</button>
        </div>
        {f.medical && <label>Что случилось?<input value={f.medical_note} onChange={(e) => set("medical_note")(e.target.value)} placeholder="давление, травма, диабет…" /></label>}
        <label>Комментарий<textarea rows="2" value={f.comment} onChange={(e) => set("comment")(e.target.value)} /></label>
        <label className="photo-in">{f.photo ? <img src={f.photo} alt="Фото" /> : "Добавить фото (необязательно)"}<input type="file" accept="image/*" capture="environment" onChange={photo} hidden /></label>
        {err && <div className="err">{err}</div>}
        <button className="sos-btn" disabled={busy}>{busy ? "Отправляем…" : "ОТПРАВИТЬ SOS"}</button>
        <p className="muted small">Данные увидят только диспетчеры экстренных служб.</p>
      </form>
    </div>
  );
}

export function Track({ token }) {
  const [s, setS] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    const load = () => api("/api/v1/public/sos/" + token).then(setS).catch((e) => setErr(e.message));
    load(); const t = setInterval(load, 8000); return () => clearInterval(t);
  }, [token]);
  const steps = ["new", "assigned", "en_route", "on_scene", "resolved"];
  const idx = s ? steps.indexOf(s.status) : -1;
  return (
    <div className="sos-page">
      <header className="sos-top"><img src="/logo.png" alt="ARLAN" /><a href="tel:112" className="call112">Позвонить 112</a></header>
      <div className="sos-form">
        <h1>Вызов принят</h1>
        {err && <div className="err">{err}</div>}
        {s && <>
          <p className="muted">Вызов №{s.id}. Оставайтесь на месте, держите телефон рядом. Экран обновляется сам.</p>
          <ol className="track">{steps.map((st, i) => <li key={st} className={i <= idx ? "on" : ""}>{STATUS[st]}</li>)}</ol>
          {s.unit && <div className="geo ok">К вам едет: <b>{s.unit.callsign}</b> ({KIND[s.unit.kind]}){s.eta_min != null ? ` · примерно ${s.eta_min} мин` : ""}</div>}
          {!s.unit && <div className="geo">Диспетчер подбирает бригаду…</div>}
          <ul className="tips"><li>Поднимитесь как можно выше, не заходите в воду.</li><li>Отключите электричество и газ, если это безопасно.</li><li>Подайте знак: фонарик, яркая ткань.</li></ul>
        </>}
        <a href="#sos" className="muted">Отправить ещё один вызов</a>
      </div>
    </div>
  );
}
