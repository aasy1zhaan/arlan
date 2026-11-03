import { useEffect, useState } from "react";
import { api, auth, can } from "./api.js";
import Login from "./pages/Login.jsx";
import SosPublic, { Track } from "./pages/SosPublic.jsx";
import Situation from "./pages/Situation.jsx";
import Dispatch from "./pages/Dispatch.jsx";
import Incidents from "./pages/Incidents.jsx";
import Alerts from "./pages/Alerts.jsx";
import Scenarios from "./pages/Scenarios.jsx";
import Chat from "./pages/Chat.jsx";
import Crew from "./pages/Crew.jsx";
import Admin from "./pages/Admin.jsx";
import Icon from "./Icon.jsx";

const SECTIONS = [
  { id: "situation", title: "Обстановка", icon: "map", perm: "map.view", el: Situation },
  { id: "dispatch", title: "Диспетчерская", icon: "sos", perm: "sos.view", el: Dispatch },
  { id: "crew", title: "Моя задача", icon: "boat", perm: "unit.self", el: Crew },
  { id: "incidents", title: "Инциденты", icon: "flag", perm: "incident.view", el: Incidents },
  { id: "alerts", title: "Оповещения", icon: "bell", perm: "alert.prepare", el: Alerts },
  { id: "scenarios", title: "Сценарии", icon: "wave", perm: "scenario.run", el: Scenarios },
  { id: "assistant", title: "ИИ-ассистент", icon: "spark", perm: "assistant.use", el: Chat },
  { id: "admin", title: "Администрирование", icon: "shield", perm: "user.manage", alt: "audit.view", el: Admin },
];

function useHash() {
  const [h, setH] = useState(location.hash);
  useEffect(() => { const f = () => setH(location.hash); addEventListener("hashchange", f); return () => removeEventListener("hashchange", f); }, []);
  return h;
}

export default function App() {
  const hash = useHash();
  const [user, setUser] = useState(null);
  const [checked, setChecked] = useState(false);
  const [drawer, setDrawer] = useState(false);

  useEffect(() => {
    const out = () => setUser(null);
    addEventListener("arlan:logout", out);
    if (auth.token) api("/api/v1/auth/me").then(setUser).catch(() => setUser(null)).finally(() => setChecked(true));
    else setChecked(true);
    return () => removeEventListener("arlan:logout", out);
  }, []);

  if (hash.startsWith("#sos")) return <SosPublic />;
  if (hash.startsWith("#track/")) return <Track token={hash.slice(7)} />;
  if (!checked) return <div className="splash"><img src="/logo.png" alt="ARLAN" /></div>;
  if (!user) return <Login onLogin={(t, u) => { auth.token = t; setUser(u); location.hash = "#/" + (u.role === "crew" ? "crew" : u.role === "dispatcher" ? "dispatch" : "situation"); }} />;

  const allowed = SECTIONS.filter((s) => can(user, s.perm) || (s.alt && can(user, s.alt)));
  const cur = allowed.find((s) => hash === "#/" + s.id) || allowed[0];
  const Page = cur.el;
  return (
    <div className="shell">
      <nav className="side glass" aria-label="Разделы">
        <a href="#/situation" className="side-logo"><img src="/logo.png" alt="ARLAN" /></a>
        {allowed.map((s) => (
          <a key={s.id} href={"#/" + s.id} className={"side-item" + (cur.id === s.id ? " on" : "")} title={s.title}>
            <Icon name={s.icon} /><span>{s.title}</span>
          </a>
        ))}
        <div className="side-sp" />
        <a href="#sos" className="side-item sos-link" title="SOS-портал жителей" target="_blank" rel="noreferrer"><Icon name="phone" /><span>Портал SOS</span></a>
        <div className="side-user">
          <div className="avatar">{user.name.split(" ").map((w) => w[0]).slice(0, 2).join("")}</div>
          <div className="side-user-t"><b>{user.name}</b><small>{user.role_title}{user.service_title ? " · " + user.service_title : ""}</small></div>
          <button className="round" title="Выйти" onClick={() => { auth.token = ""; setUser(null); location.hash = ""; }}><Icon name="logout" /></button>
        </div>
      </nav>
      <main className="main">
        <Page user={user} />
      </main>
      {cur.id !== "assistant" && can(user, "assistant.use") && (
        <>
          <button className="fab" onClick={() => setDrawer(!drawer)} aria-label="ИИ-ассистент"><Icon name="spark" /><span>Спросить ARLAN</span></button>
          {drawer && (
            <aside className="drawer glass" aria-label="ИИ-ассистент">
              <Chat user={user} compact context={cur.title} onClose={() => setDrawer(false)} />
            </aside>
          )}
        </>
      )}
    </div>
  );
}
