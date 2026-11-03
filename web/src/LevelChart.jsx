import { fmt } from "./api.js";

// Observed level (left 42%) + 15-day forecast with P10-P90 hatched band (right 58%).
export default function LevelChart({ state, day = 0, compare }) {
  const W = 360, H = 130, L = 6, R = 6, T = 22, B = 22;
  const all = state.level.series;
  const src = all.length ? all[all.length - 1].src : null;
  const hist = all.filter((p) => p.src === src).filter((_, i, a) => i % 3 === 0 || i === a.length - 1);
  const fc = state.forecast;
  const vals = [...hist.map((p) => p.m), ...fc.p10, ...fc.p90, state.level.danger_m, ...(compare ? compare.p50 : [])];
  const lo = Math.min(...vals) - 0.2, hi = Math.max(...vals) + 0.2;
  const nh = Math.max(2, hist.length), nf = fc.p50.length, split = L + (W - L - R) * 0.42;
  const x = (i) => (i <= nh - 1 ? L + (split - L) * (i / (nh - 1)) : split + (W - R - split) * ((i - nh + 1) / nf));
  const y = (v) => T + (H - T - B) * (1 - (v - lo) / (hi - lo));
  const k = nh - 1;
  const p90 = fc.p90.map((v, i) => `${x(k + 1 + i)},${y(v)}`).join(" ");
  const p10 = [...fc.p10].reverse().map((v, i) => `${x(k + fc.p10.length - i)},${y(v)}`).join(" ");
  const sel = day === 0 ? { i: k, v: state.level.now_m } : { i: k + day, v: fc.p50[day - 1] };
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="levelchart" role="img" aria-label="Уровень Есиля: наблюдения и прогноз">
      <defs>
        <pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <rect width="6" height="6" fill="rgba(255,255,255,0.06)" /><line x1="0" y1="0" x2="0" y2="6" stroke="rgba(255,255,255,0.45)" strokeWidth="2.2" />
        </pattern>
      </defs>
      <line x1={L} x2={W - R} y1={y(state.level.danger_m)} y2={y(state.level.danger_m)} stroke="#FF4D5E" strokeDasharray="3 4" />
      <text x={L} y={y(state.level.danger_m) - 6} className="t-danger">опасно {fmt(state.level.danger_m)} м</text>
      <polygon points={`${x(k)},${y(state.level.now_m)} ${p90} ${p10}`} fill="url(#hatch)" />
      {hist.length > 1 && <polyline points={hist.map((p, i) => `${x(i)},${y(p.m)}`).join(" ")} fill="none" stroke="rgba(255,255,255,0.75)" strokeWidth="1.6" />}
      {compare && <polyline points={`${x(k)},${y(state.level.now_m)} ` + compare.p50.map((v, i) => `${x(k + 1 + i)},${y(v)}`).join(" ")} fill="none" stroke="rgba(255,255,255,.45)" strokeWidth="1.4" strokeDasharray="4 4" />}
      <polyline points={`${x(k)},${y(state.level.now_m)} ` + fc.p50.map((v, i) => `${x(k + 1 + i)},${y(v)}`).join(" ")} fill="none" stroke="#CBF34D" strokeWidth="2" />
      {[0, 4, 9, 14].filter((d) => d < nf).map((d) => <circle key={d} cx={x(k + 1 + d)} cy={y(fc.p50[d])} r="2.6" fill="#fff" />)}
      <line x1={x(sel.i)} x2={x(sel.i)} y1={T - 4} y2={H - B} stroke="rgba(203,243,77,0.6)" />
      <g transform={`translate(${Math.min(W - 44, Math.max(4, x(sel.i) - 22))},${Math.max(2, y(sel.v) - 30)})`}>
        <rect width="44" height="20" rx="10" fill="#CBF34D" />
        <text x="22" y="14" textAnchor="middle" className="t-chip">{fmt(sel.v, 1)}м</text>
      </g>
      <text x={L} y={H - 4} className="t-axis">−72 ч</text>
      <text x={x(k)} y={H - 4} className="t-axis" textAnchor="middle">сейчас</text>
      <text x={x(k + 7)} y={H - 4} className="t-axis" textAnchor="middle">+7 д</text>
      <text x={W - R} y={H - 4} className="t-axis" textAnchor="end">+15 д</text>
    </svg>
  );
}
