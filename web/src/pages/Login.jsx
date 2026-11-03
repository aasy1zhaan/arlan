import { useEffect, useState } from "react";
import { api } from "../api.js";

export default function Login({ onLogin }) {
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [demo, setDemo] = useState([]);
  useEffect(() => { api("/api/v1/auth/demo-accounts").then(setDemo).catch((e) => setErr(e.message)); }, []);

  async function submit(e) {
    e.preventDefault();
    setBusy(true); setErr("");
    try { const r = await api("/api/v1/auth/login", { method: "POST", body: { email, password: pw } }); onLogin(r.token, r.user); }
    catch (x) { setErr(x.message); } finally { setBusy(false); }
  }
  async function quick(em) {
    setBusy(true); setErr("");
    try { const r = await api("/api/v1/auth/demo/" + encodeURIComponent(em), { method: "POST" }); onLogin(r.token, r.user); }
    catch (x) { setErr(x.message); } finally { setBusy(false); }
  }

  return (
    <div className="login">
      <div className="login-art" aria-hidden="true" />
      <div className="login-box">
        <img src="/logo.png" alt="ARLAN" className="login-logo" />
        <h1 className="login-h">Город,<br />который слышит воду</h1>
        <p className="muted">Платформа раннего предупреждения о паводках · Петропавловск</p>
        <form onSubmit={submit} className="glass login-form">
          <label htmlFor="em">Рабочая почта</label>
          <input id="em" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
          <label htmlFor="pw">Пароль</label>
          <input id="pw" type="password" autoComplete="current-password" value={pw} onChange={(e) => setPw(e.target.value)} required />
          {err && <div className="err">{err}</div>}
          <button className="btn-lime" disabled={busy}>{busy ? "Входим…" : "Войти"}</button>
        </form>
        {demo.length > 0 && (
          <div className="demo-roles">
            <span className="muted">Демо-доступ: войти одной кнопкой под ролью</span>
            <div className="chips">
              {demo.map((d) => <button key={d.email} className="chip" disabled={busy} onClick={() => quick(d.email)} title={d.role_title}>{d.name}</button>)}
            </div>
          </div>
        )}
        <a className="sos-cta" href="#sos">Я житель, мне нужна помощь → SOS</a>
      </div>
    </div>
  );
}
