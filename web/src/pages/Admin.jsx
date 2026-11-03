import { useEffect, useState } from "react";
import { api, can } from "../api.js";

export default function Admin({ user }) {
  const [tab, setTab] = useState(can(user, "user.manage") ? "users" : "audit");
  const [users, setUsers] = useState([]);
  const [roles, setRoles] = useState({ roles: [], permissions: {}, services: {} });
  const [audit, setAudit] = useState([]);
  const [nu, setNu] = useState(null);
  const [nr, setNr] = useState(null);
  const [msg, setMsg] = useState("");
  const load = () => {
    if (can(user, "user.manage")) { api("/api/v1/admin/users").then(setUsers).catch((e) => setMsg(e.message)); }
    api("/api/v1/admin/roles").then(setRoles).catch(() => {});
    if (can(user, "audit.view")) api("/api/v1/admin/audit").then(setAudit).catch(() => {});
  };
  useEffect(load, []);
  const roleTitle = (k) => roles.roles.find((r) => r.key === k)?.title || k;

  async function addUser(e) {
    e.preventDefault();
    try { const r = await api("/api/v1/admin/users", { method: "POST", body: nu }); setMsg(r.temporary_password ? `Создан. Временный пароль: ${r.temporary_password}` : "Создан"); setNu(null); load(); }
    catch (x) { setMsg(x.message); }
  }
  async function toggle(u) {
    try { await api("/api/v1/admin/users/" + u.id, { method: "PATCH", body: { ...u, active: !u.active, password: null } }); load(); } catch (x) { setMsg(x.message); }
  }
  async function saveRole(e) {
    e.preventDefault();
    try { await api("/api/v1/admin/roles", { method: "POST", body: nr }); setNr(null); load(); } catch (x) { setMsg(x.message); }
  }

  return (
    <div className="page">
      <div className="page-h"><h1>Администрирование</h1>
        <div className="chips">
          {can(user, "user.manage") && <button className={"chip" + (tab === "users" ? " on" : "")} onClick={() => setTab("users")}>Пользователи</button>}
          {can(user, "user.manage") && <button className={"chip" + (tab === "roles" ? " on" : "")} onClick={() => setTab("roles")}>Роли и права</button>}
          {can(user, "audit.view") && <button className={"chip" + (tab === "audit" ? " on" : "")} onClick={() => setTab("audit")}>Журнал действий</button>}
        </div>
      </div>
      {msg && <div className="note-line">{msg}</div>}

      {tab === "users" && <>
        <button className="btn-lime" onClick={() => setNu({ email: "", name: "", role: "duty", service: null, password: "" })}>+ Пользователь</button>
        {nu && <form className="glass form wide" onSubmit={addUser}>
          <label>Имя<input required value={nu.name} onChange={(e) => setNu({ ...nu, name: e.target.value })} /></label>
          <label>Почта<input required type="email" value={nu.email} onChange={(e) => setNu({ ...nu, email: e.target.value })} /></label>
          <label>Роль<select value={nu.role} onChange={(e) => setNu({ ...nu, role: e.target.value })}>{roles.roles.map((r) => <option key={r.key} value={r.key}>{r.title}</option>)}</select></label>
          <label>Служба<select value={nu.service || ""} onChange={(e) => setNu({ ...nu, service: e.target.value || null })}><option value="">—</option>{Object.entries(roles.services).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
          <label>Пароль (пусто = сгенерировать)<input value={nu.password} onChange={(e) => setNu({ ...nu, password: e.target.value })} /></label>
          <div className="row-btns"><button className="btn-lime">Создать</button><button type="button" className="btn-ghost" onClick={() => setNu(null)}>Отмена</button></div>
        </form>}
        <div className="scroll"><table className="tbl"><thead><tr><th>Имя</th><th>Почта</th><th>Роль</th><th>Служба</th><th>Статус</th><th /></tr></thead><tbody>
          {users.map((u) => <tr key={u.id}><td>{u.name}</td><td>{u.email}</td><td>{roleTitle(u.role)}</td><td>{roles.services[u.service] || "—"}</td><td>{u.active ? "активен" : "отключён"}</td>
            <td>{u.id !== user.id && <button className="btn-ghost" onClick={() => toggle(u)}>{u.active ? "Отключить" : "Включить"}</button>}</td></tr>)}
        </tbody></table></div>
      </>}

      {tab === "roles" && <>
        <button className="btn-lime" onClick={() => setNr({ key: "", title: "", permissions: [] })}>+ Своя роль</button>
        {nr && <form className="glass form wide" onSubmit={saveRole}>
          <label>Код (латиницей)<input required pattern="[a-z_]+" value={nr.key} onChange={(e) => setNr({ ...nr, key: e.target.value })} /></label>
          <label>Название<input required value={nr.title} onChange={(e) => setNr({ ...nr, title: e.target.value })} /></label>
          <div className="perm-grid">{Object.entries(roles.permissions).map(([k, v]) => <label key={k} className="check"><input type="checkbox" checked={nr.permissions.includes(k)} onChange={(e) => setNr({ ...nr, permissions: e.target.checked ? [...nr.permissions, k] : nr.permissions.filter((x) => x !== k) })} />{v}</label>)}</div>
          <div className="row-btns"><button className="btn-lime">Сохранить</button><button type="button" className="btn-ghost" onClick={() => setNr(null)}>Отмена</button></div>
        </form>}
        <div className="scroll"><table className="tbl matrix"><thead><tr><th>Право</th>{roles.roles.map((r) => <th key={r.key} title={r.title}>{r.title.split(" (")[0]}</th>)}</tr></thead><tbody>
          {Object.entries(roles.permissions).map(([k, v]) => <tr key={k}><td>{v}</td>{roles.roles.map((r) => <td key={r.key} className="c">{r.permissions.includes(k) ? "●" : ""}</td>)}</tr>)}
        </tbody></table></div>
      </>}

      {tab === "audit" && <div className="scroll"><table className="tbl"><thead><tr><th>Время</th><th>Кто</th><th>Действие</th><th>Объект</th></tr></thead><tbody>
        {audit.map((a) => <tr key={a.id}><td>{new Date(a.ts).toLocaleString("ru-RU")}</td><td>{a.user_name}</td><td className="mono">{a.action}</td><td className="mono">{a.target}</td></tr>)}
      </tbody></table></div>}
    </div>
  );
}
