import { useEffect, useState } from "react";
import { ago, api, can, SEV } from "../api.js";

const SEVRU = { low: "низкая", medium: "средняя", high: "высокая", critical: "критическая" };
const STRU = { open: "Открыт", in_progress: "В работе", resolved: "Закрыт" };

export default function Incidents({ user }) {
  const [items, setItems] = useState([]);
  const [sel, setSel] = useState(null);
  const [note, setNote] = useState("");
  const [form, setForm] = useState(null);
  const [all, setAll] = useState(false);
  const [err, setErr] = useState("");
  const load = () => api("/api/v1/incidents?status=" + (all ? "all" : "open")).then(setItems).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, [all]);
  const cur = items.find((i) => i.id === sel) || items[0];
  const edit = can(user, "incident.manage");

  async function upd(body) { try { await api("/api/v1/incidents/" + cur.id, { method: "PATCH", body }); setNote(""); load(); } catch (e) { setErr(e.message); } }
  async function create(e) {
    e.preventDefault();
    try { const r = await api("/api/v1/incidents", { method: "POST", body: form }); setForm(null); await load(); setSel(r.id); } catch (x) { setErr(x.message); }
  }

  return (
    <div className="page two">
      <section className="list-col">
        <div className="page-h"><h1>Инциденты</h1>{edit && <button className="btn-lime" onClick={() => setForm({ title: "", kind: "flood", severity: "medium", note: "" })}>+ Новый</button>}</div>
        <label className="check"><input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} /> Показать закрытые</label>
        {err && <div className="err">{err}</div>}
        {items.map((i) => (
          <button key={i.id} className={"inc-item" + (cur && cur.id === i.id ? " on" : "")} onClick={() => setSel(i.id)}>
            <i style={{ background: SEV[i.severity] }} /><span><b>{i.title}</b><small>{STRU[i.status]} · {i.assignee || "без исполнителя"} · {ago(i.created_at)}</small></span>
          </button>
        ))}
        {items.length === 0 && <p className="muted">Открытых инцидентов нет.</p>}
      </section>
      <section className="detail-col glass">
        {form ? (
          <form onSubmit={create} className="form">
            <h2>Новый инцидент</h2>
            <label>Название<input required value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></label>
            <label>Тип<select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}><option value="dam">Дамба</option><option value="flood">Подтопление</option><option value="rain">Ливень</option><option value="sos">Спасение</option><option value="infrastructure">Инфраструктура</option></select></label>
            <label>Серьёзность<select value={form.severity} onChange={(e) => setForm({ ...form, severity: e.target.value })}>{Object.entries(SEVRU).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
            <label>Описание<textarea rows="3" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} /></label>
            <div className="row-btns"><button className="btn-lime">Создать</button><button type="button" className="btn-ghost" onClick={() => setForm(null)}>Отмена</button></div>
          </form>
        ) : cur ? (
          <>
            <div className="inc-h"><span className="pill" style={{ background: SEV[cur.severity] }}>{SEVRU[cur.severity]}</span><span className="muted">№{cur.id} · {STRU[cur.status]}</span></div>
            <h2>{cur.title}</h2>
            {edit && <div className="row-btns">
              {cur.status !== "in_progress" && cur.status !== "resolved" && <button className="btn-ghost" onClick={() => upd({ status: "in_progress", assignee_id: user.id })}>Взять в работу</button>}
              {cur.status !== "resolved" && <button className="btn-lime" onClick={() => upd({ status: "resolved", note: "Инцидент закрыт" })}>Закрыть</button>}
            </div>}
            <ol className="timeline">
              {cur.events.map((e) => <li key={e.id}><small>{new Date(e.ts).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })} · {e.user_name}</small><p>{e.text}</p></li>)}
            </ol>
            {edit && cur.status !== "resolved" && <form className="note" onSubmit={(e) => { e.preventDefault(); note.trim() && upd({ note }); }}>
              <input placeholder="Добавить запись в ленту…" value={note} onChange={(e) => setNote(e.target.value)} aria-label="Запись" /><button className="btn-lime">Добавить</button>
            </form>}
          </>
        ) : <p className="muted">Выберите инцидент.</p>}
      </section>
    </div>
  );
}
