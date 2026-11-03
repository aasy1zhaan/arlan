// Routes for rescue units. Road units: OSRM public router; boats: straight line over water.
// The returned path is split into dry and flooded parts using the 3D terrain under the map.
export async function buildRoute(from, to, kind) {
  const water = kind === "boat" || kind === "amphibious";
  if (water) return { coords: [from, to], source: "по воде (прямая)", water: true };
  try {
    const url = `https://router.project-osrm.org/route/v1/driving/${from[0]},${from[1]};${to[0]},${to[1]}?overview=full&geometries=geojson`;
    const r = await fetch(url);
    const j = await r.json();
    if (j.routes && j.routes[0]) {
      return { coords: j.routes[0].geometry.coordinates, source: "по дорогам (OSRM)", km: j.routes[0].distance / 1000, min: j.routes[0].duration / 60 };
    }
  } catch { /* router unreachable: fall back */ }
  return { coords: [from, to], source: "прямая (маршрутизатор недоступен)" };
}

// Split coords into runs of dry / wet using a terrain sampler: elev(lngLat) -> metres or null
export function splitByFlood(coords, elev, floodElev) {
  if (!elev || floodElev == null) return { dry: [coords], wet: [] };
  const dense = [];
  for (let i = 0; i < coords.length - 1; i++) {
    const [a, b] = [coords[i], coords[i + 1]];
    const n = Math.max(1, Math.ceil(Math.hypot(b[0] - a[0], b[1] - a[1]) / 0.0004));
    for (let k = 0; k < n; k++) dense.push([a[0] + ((b[0] - a[0]) * k) / n, a[1] + ((b[1] - a[1]) * k) / n]);
  }
  dense.push(coords[coords.length - 1]);
  const dry = [], wet = [];
  let cur = [dense[0]], curWet = isWet(dense[0]);
  function isWet(p) { const e = elev(p); return e != null && e < floodElev; }
  for (let i = 1; i < dense.length; i++) {
    const w = isWet(dense[i]);
    cur.push(dense[i]);
    if (w !== curWet) { (curWet ? wet : dry).push(cur); cur = [dense[i]]; curWet = w; }
  }
  (curWet ? wet : dry).push(cur);
  return { dry, wet };
}
