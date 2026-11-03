import { useEffect, useState } from "react";
import { ago, api, can } from "../api.js";

const DIST = { podgora: "Подгора", kozhevenny: "Кожевенный", kosogor: "Косогор", zarechny: "Заречный", center: "Центр" };
const ST = { pending: "Ждёт утверждения", sent: "Отправлено", rejected: "Отклонено", draft: "Черновик", approved: "Утверждено" };

export default function Alerts({ user }) {
  const [items, setItems] = useState([]);
  const [f, setF] = useState(null);
  const [err, setErr] = useState("");
  const [toast, setToast] = useState("");
  const load = () => api("/api/v1/notifications").then(setItems).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, []);
  useEffect(() => { if (toast) { const t = setTimeout(() => setToast(""), 2600); return () => clearTimeout(t); } }, [toast]);

  async function decide(id, approve) {
    try { const r = await api(`/api/v1/notifications/${id}/decide`, { method: "POST", body: { approve } }); setToast(approve ? `Отправлено: ${r.recipients} получателей` : "Отклонено"); load(); }
    catch (e) { setToast(e.message); }
  }
  async function create(e) {
    e.preventDefault();
    try { await api("/api/v1/notifications", { method: "POST", body: f }); setF(null); setToast("Отправлено на утверждение"); load(); } catch (x) { setErr(x.message); }
  }

  return (
    <div className="page">
      <div className="page-h"><h1>Оповещения жителей</h1><button className="btn-lime" onClick={() => setF({ title: "", text_ru: "", text_kk: "", districts: [], channels: ["telegram", "sms"] })}>+ Подготовить</button></div>
      <p className="muted">Дежурный готовит текст, руководитель утверждает. Рассылка идёт только жителям выбранных районов. Подготовить текст можно и через ИИ-ассистента.</p>
      {err && <div className="err">{err}</div>}
      {f && (
        <form className="glass form wide" onSubmit={create}>
          <label>Заголовок<input required value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></label>
          <label>Текст на русском<textarea required rows="3" value={f.text_ru} onChange={(e) => setF({ ...f, text_ru: e.target.value })} /></label>
          <label>Текст на казахском<textarea rows="3" value={f.text_kk} onChange={(e) => setF({ ...f, text_kk: e.target.value })} /></label>
          <fieldset><legend>Районы</legend><div className="chips">{Object.entries(DIST).map(([k, v]) => <button type="button" key={k} className={"chip" + (f.districts.includes(k) ? " on" : "")} onClick={() => setF({ ...f, districts: f.districts.includes(k) ? f.districts.filter((x) => x !== k) : [...f.districts, k] })}>{v}</button>)}</div></fieldset>
          <div className="row-btns"><button className="btn-lime" disabled={!f.districts.length}>На утверждение</button><button type="button" className="btn-ghost" onClick={() => setF(null)}>Отмена</button></div>
        </form>
      )}
      <div className="alert-list">
        {items.map((n) => (
          <article key={n.id} className={"glass alert-card " + n.status}>
            <header><b>{n.title}</b><span className={"st " + n.status}>{ST[n.status]}</span></header>
            <p>{n.text_ru}</p>
            {n.text_kk && <p className="muted">{n.text_kk}</p>}
            <footer>
              <span className="muted">{n.districts.map((d) => DIST[d] || d).join(", ")} · {n.status === "sent" ? `${n.recipients} получателей` : `~${n.recipients_est} получателей`} · {ago(n.created_at)}</span>
              {n.status === "pending" && can(user, "alert.approve") && <span className="row-btns"><button className="btn-lime" onClick={() => decide(n.id, true)}>Утвердить и отправить</button><button className="btn-ghost" onClick={() => decide(n.id, false)}>Отклонить</button></span>}
            </footer>
          </article>
        ))}
      </div>
      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}
