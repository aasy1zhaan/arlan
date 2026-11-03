// Minimal line icons (1.6 stroke), one component so the set stays consistent.
const P = {
  map: "M3 6l6-3 6 3 6-3v15l-6 3-6-3-6 3V6zm6-3v15m6-12v15",
  sos: "M12 3a9 9 0 100 18 9 9 0 000-18zm0 5v5m0 3h.01",
  boat: "M3 15l2 4h14l2-4H3zm3 0V9h9l3 6M10 9V5h3",
  flag: "M5 21V4m0 0h11l-2 4 2 4H5",
  bell: "M12 3a6 6 0 00-6 6v4l-2 3h16l-2-3V9a6 6 0 00-6-6zm-2 16a2 2 0 004 0",
  wave: "M2 12c3-3 5-3 8 0s5 3 8 0 3-1 4 0M2 17c3-3 5-3 8 0s5 3 8 0 3-1 4 0M2 7c3-3 5-3 8 0s5 3 8 0 3-1 4 0",
  spark: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3zm7 12l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8L19 15z",
  shield: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3z",
  phone: "M5 4h4l2 5-2.5 1.5a11 11 0 005 5L15 13l5 2v4a2 2 0 01-2 2A16 16 0 013 6a2 2 0 012-2z",
  logout: "M15 4h4v16h-4M10 8l-4 4 4 4M6 12h10",
  send: "M4 12l16-8-6 16-2-6-8-2z",
  plus: "M12 5v14M5 12h14",
  clip: "M8 12l6-6a3 3 0 014 4l-8 8a5 5 0 01-7-7l7-7",
  close: "M6 6l12 12M18 6L6 18",
  check: "M5 12l5 5 9-10",
  route: "M6 19a2 2 0 100-4 2 2 0 000 4zm12-10a2 2 0 100-4 2 2 0 000 4zM6 15V9a3 3 0 013-3h3m0 12h3a3 3 0 003-3V9",
  trash: "M5 7h14M10 11v6m4-6v6M6 7l1 13h10l1-13M9 7V4h6v3",
};
export default function Icon({ name, size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={P[name] || P.plus} />
    </svg>
  );
}
