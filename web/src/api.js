// Thin API client: token in localStorage, JSON helpers, SSE streaming for the assistant.
export const API = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "") || (location.hostname === "localhost" ? "http://localhost:8000" : "");

const KEY = "arlan.token";
export const auth = {
  get token() { try { return localStorage.getItem(KEY) || ""; } catch { return ""; } },
  set token(v) { try { v ? localStorage.setItem(KEY, v) : localStorage.removeItem(KEY); } catch { /* storage blocked */ } },
};

export class ApiError extends Error {
  constructor(status, msg) { super(msg); this.status = status; }
}

export async function api(path, { method = "GET", body, raw } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth.token) headers.Authorization = "Bearer " + auth.token;
  let r;
  try {
    r = await fetch(API + path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  } catch {
    throw new ApiError(0, "Сервер ARLAN недоступен. Проверьте подключение.");
  }
  if (raw) return r;
  let data = null;
  try { data = await r.json(); } catch { /* empty */ }
  if (!r.ok) {
    if (r.status === 401 && path !== "/api/v1/auth/login") { auth.token = ""; window.dispatchEvent(new Event("arlan:logout")); }
    throw new ApiError(r.status, (data && (data.detail?.[0]?.msg || data.detail)) || `Ошибка ${r.status}`);
  }
  return data;
}

// POST and read Server-Sent Events: onEvent({type, ...}) for each event
export async function stream(path, body, onEvent) {
  const r = await api(path, { method: "POST", body, raw: true });
  if (!r.ok) {
    let msg = `Ошибка ${r.status}`;
    try { msg = (await r.json()).detail || msg; } catch { /* */ }
    onEvent({ type: "error", text: msg });
    onEvent({ type: "done" });
    return;
  }
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, i);
      buf = buf.slice(i + 2);
      const line = chunk.split("\n").find((l) => l.startsWith("data: "));
      if (line) { try { onEvent(JSON.parse(line.slice(6))); } catch { /* skip */ } }
    }
  }
}

export const can = (user, perm) => !!user && user.permissions.includes(perm);
export const fmt = (v, d = 2) => (v == null || Number.isNaN(+v) ? "—" : (+v).toFixed(d));
export const ago = (iso) => {
  const m = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  return m < 1 ? "только что" : m < 60 ? `${m} мин назад` : `${Math.floor(m / 60)} ч ${m % 60} мин назад`;
};
export const WATER = { none: "воды нет", ankle: "по щиколотку", knee: "по колено", waist: "по пояс", chest: "по грудь", roof: "на крыше" };
export const SERVICE = { emergency: "МЧС 112", ambulance: "Скорая 103", police: "Полиция 102" };
export const KIND = { boat: "Лодка", amphibious: "Амфибия", rescue_truck: "Спасатели", ambulance: "Скорая", patrol: "Патруль" };
export const STATUS = { new: "Новый", assigned: "Назначен", en_route: "В пути", on_scene: "На месте", resolved: "Завершён", cancelled: "Отменён" };
export const SEV = { low: "#7FE0A8", medium: "#F2C94C", high: "#FF8A3D", critical: "#FF4D5E" };
