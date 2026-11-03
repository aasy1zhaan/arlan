import { useEffect, useRef, useState } from "react";
import { marked } from "marked";
import DOMPurify from "dompurify";
import { api, stream } from "../api.js";
import Icon from "../Icon.jsx";

marked.setOptions({ gfm: true, breaks: true });
const md = (t) => ({ __html: DOMPurify.sanitize(marked.parse(t || "")) });
const TOOL = {
  get_situation: "Смотрю обстановку", run_scenario: "Считаю сценарий", list_sos: "Смотрю очередь SOS", list_units: "Смотрю бригады",
  recommend_units: "Подбираю бригаду", assign_unit: "Назначаю бригаду", list_incidents: "Смотрю инциденты",
  create_incident: "Создаю инцидент", draft_alert: "Готовлю оповещение",
};
const SUGGEST = [
  "Кого спасать первым и какие бригады отправить?",
  "Что будет, если сброс из Сергеевского увеличат на 80 м³/с?",
  "Какая дамба самая опасная и почему?",
  "Подготовь оповещение для жителей Подгоры на русском и казахском",
  "Сделай короткую сводку для акима на 5 строк",
];

export default function Chat({ user, compact, context, onClose }) {
  const [convs, setConvs] = useState([]);
  const [cid, setCid] = useState(null);
  const [msgs, setMsgs] = useState([]);
  const [text, setText] = useState("");
  const [img, setImg] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const end = useRef(null);
  const fileRef = useRef(null);

  const loadConvs = () => api("/api/v1/chat").then(setConvs).catch((e) => setErr(e.message));
  useEffect(() => { loadConvs(); }, []);
  useEffect(() => { if (cid) api("/api/v1/chat/" + cid).then((c) => setMsgs(c.messages)).catch((e) => setErr(e.message)); else setMsgs([]); }, [cid]);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [msgs]);

  async function send(q) {
    const t = (q ?? text).trim();
    if (!t || busy) return;
    setBusy(true); setErr(""); setText("");
    let id = cid;
    try {
      if (!id) { id = (await api("/api/v1/chat", { method: "POST", body: { title: t.slice(0, 60) } })).id; setCid(id); }
    } catch (e) { setErr(e.message); setBusy(false); return; }
    const image = img; setImg(null);
    setMsgs((m) => [...m, { role: "user", text: t, image }, { role: "assistant", text: "", tools: [], live: [] }]);
    const patch = (fn) => setMsgs((m) => { const c = [...m]; c[c.length - 1] = fn({ ...c[c.length - 1] }); return c; });
    await stream(`/api/v1/chat/${id}/send`, { text: t, context, image }, (ev) => {
      if (ev.type === "text") patch((a) => ({ ...a, text: a.text + ev.delta }));
      if (ev.type === "tool") patch((a) => ({ ...a, live: [...(a.live || []), { name: ev.name, done: false }] }));
      if (ev.type === "tool_result") patch((a) => ({ ...a, live: a.live.map((x) => (x.name === ev.name && !x.done ? { ...x, done: true, ok: ev.ok } : x)) }));
      if (ev.type === "error") patch((a) => ({ ...a, error: ev.text }));
    });
    setBusy(false);
    loadConvs();
  }

  function pick(e) {
    const f = e.target.files?.[0];
    if (!f) return;
    if (f.size > 2_000_000) { setErr("Фото больше 2 МБ"); return; }
    const r = new FileReader();
    r.onload = () => setImg(r.result);
    r.readAsDataURL(f);
  }

  async function del(id) {
    await api("/api/v1/chat/" + id, { method: "DELETE" }).catch(() => {});
    if (id === cid) setCid(null);
    loadConvs();
  }

  return (
    <div className={"chat" + (compact ? " compact" : "")}>
      {!compact && (
        <aside className="chat-list">
          <button className="btn-lime wide" onClick={() => setCid(null)}><Icon name="plus" /> Новый чат</button>
          <div className="chat-convs">
            {convs.map((c) => (
              <div key={c.id} className={"conv" + (c.id === cid ? " on" : "")}>
                <button onClick={() => setCid(c.id)}>{c.title}</button>
                <button className="x" title="Удалить" onClick={() => del(c.id)}><Icon name="trash" size={14} /></button>
              </div>
            ))}
          </div>
        </aside>
      )}
      <section className="chat-main">
        <header className="chat-h">
          <div><b>ARLAN</b><small className="muted"> · ИИ-ассистент · видит данные платформы в пределах ваших прав</small></div>
          {compact && <div className="chat-h-r"><a href="#/assistant" className="btn-ghost">Открыть полностью</a><button className="round" onClick={onClose} aria-label="Закрыть"><Icon name="close" /></button></div>}
        </header>
        <div className="chat-scroll">
          {msgs.length === 0 && (
            <div className="chat-empty">
              <h2>Чем помочь, {user.name.split(" ")[0]}?</h2>
              <p className="muted">Спросите про обстановку, попросите посчитать сценарий, подобрать бригады или подготовить оповещение.</p>
              <div className="suggest">{SUGGEST.map((s) => <button key={s} onClick={() => send(s)}>{s}</button>)}</div>
            </div>
          )}
          {msgs.map((m, i) => (
            <div key={i} className={"msg " + m.role}>
              {m.role === "assistant" && <div className="msg-av"><Icon name="spark" size={16} /></div>}
              <div className="msg-body">
                {m.image && <img src={m.image} alt="Вложение" className="msg-img" />}
                {(m.live || []).length > 0 && <div className="tools">{m.live.map((t, j) => <span key={j} className={"tool" + (t.done ? " done" : "")}>{t.done ? <Icon name="check" size={13} /> : <i className="spin" />}{TOOL[t.name] || t.name}</span>)}</div>}
                {(m.tools || []).length > 0 && !(m.live || []).length && <div className="tools">{m.tools.map((t, j) => <span key={j} className="tool done"><Icon name="check" size={13} />{TOOL[t] || t}</span>)}</div>}
                {m.role === "user" ? <p>{m.text}</p> : <div className="md" dangerouslySetInnerHTML={md(m.text)} />}
                {m.role === "assistant" && !m.text && !m.error && busy && i === msgs.length - 1 && <div className="typing"><i /><i /><i /></div>}
                {m.error && <div className="err">{m.error}</div>}
              </div>
            </div>
          ))}
          <div ref={end} />
        </div>
        {err && <div className="err">{err}</div>}
        <form className="composer glass" onSubmit={(e) => { e.preventDefault(); send(); }}>
          {img && <div className="att"><img src={img} alt="" /><button type="button" onClick={() => setImg(null)} aria-label="Убрать фото"><Icon name="close" size={12} /></button></div>}
          <textarea rows={compact ? 2 : 3} placeholder="Напишите вопрос или задачу…" value={text} onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} aria-label="Сообщение ассистенту" />
          <div className="composer-r">
            <input type="file" accept="image/*" ref={fileRef} hidden onChange={pick} id="chat-file" />
            <button type="button" className="round" onClick={() => fileRef.current.click()} title="Прикрепить фото"><Icon name="clip" /></button>
            <button className="send" disabled={busy || !text.trim()} aria-label="Отправить"><Icon name="send" /></button>
          </div>
        </form>
      </section>
    </div>
  );
}
