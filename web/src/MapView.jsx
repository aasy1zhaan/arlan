import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import { SEGMENTS, STATIONS, mid } from "./geo.js";

const EXAG = 2.2; // flat city: exaggerate relief so the floodplain reads in 3D
const SEV = { low: "#7FE0A8", medium: "#F2C94C", high: "#FF8A3D", critical: "#FF4D5E" };
const TOKEN = import.meta.env.VITE_MAPBOX_TOKEN;
const EMPTY = { type: "FeatureCollection", features: [] };
const prioColor = (p) => (p >= 80 ? "#FF4D5E" : p >= 60 ? "#FF8A3D" : p >= 40 ? "#F2C94C" : "#7FE0A8");

function sources() {
  const sat = TOKEN
    ? { type: "raster", tiles: [`https://api.mapbox.com/v4/mapbox.satellite/{z}/{x}/{y}@2x.jpg90?access_token=${TOKEN}`], tileSize: 512, maxzoom: 19, attribution: "© Mapbox © Maxar" }
    : { type: "raster", tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"], tileSize: 256, maxzoom: 19, attribution: "Imagery © Esri, Maxar, Earthstar Geographics" };
  const dem = { type: "raster-dem", tiles: ["https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"], encoding: "terrarium", tileSize: 256, maxzoom: 14, attribution: "Terrain: Mapzen / AWS Open Data" };
  return { sat, dem, dem2: { ...dem } };
}

function floodRamp(e) {
  return ["interpolate", ["linear"], ["elevation"], e - 40, "rgba(40,170,255,0.62)", e - 0.6, "rgba(90,200,255,0.55)", e, "rgba(160,230,255,0.35)", e + 0.05, "rgba(0,0,0,0)"];
}

function lines(coordsList, props = {}) {
  return { type: "FeatureCollection", features: coordsList.filter((c) => c.length > 1).map((c) => ({ type: "Feature", properties: props, geometry: { type: "LineString", coordinates: c } })) };
}

export default function MapView({ state, waterLevel, selected, onSelect, sos = [], units = [], shelters = [], route,
  onSos, selectedSos, spin = true, onReady, initial, className = "map" }) {
  const box = useRef(null);
  const map = useRef(null);
  const marks = useRef([]);
  const [ready, setReady] = useState(false);
  const [base, setBase] = useState(null);

  useEffect(() => {
    const m = new maplibregl.Map({
      container: box.current,
      style: {
        version: 8, sources: sources(),
        layers: [
          { id: "bg", type: "background", paint: { "background-color": "#0b0f0d" } },
          { id: "sat", type: "raster", source: "sat", paint: { "raster-saturation": -0.35, "raster-brightness-max": 0.78, "raster-contrast": 0.12 } },
          { id: "hill", type: "hillshade", source: "dem2", paint: { "hillshade-exaggeration": 0.35, "hillshade-shadow-color": "#000", "hillshade-highlight-color": "rgba(255,255,255,0.05)" } },
        ],
        sky: { "sky-color": "#0d1412", "horizon-color": "#26302b", "fog-color": "#0d1412", "sky-horizon-blend": 0.6, "horizon-fog-blend": 0.7, "fog-ground-blend": 0.2 },
      },
      center: initial?.center || [69.098, 54.8885], zoom: initial?.zoom ?? 12.9, pitch: initial?.pitch ?? 64, bearing: initial?.bearing ?? -28,
      maxPitch: 80, attributionControl: { compact: true },
    });
    map.current = m;
    window.__arlanMaps = [...(window.__arlanMaps || []), m];
    m.on("error", (e) => console.warn("map error", e && e.error && e.error.message));
    m.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "bottom-right");
    let spinning = spin;
    const stop = () => { spinning = false; };
    ["mousedown", "touchstart", "wheel"].forEach((ev) => m.getCanvas().addEventListener(ev, stop, { once: true }));
    const turn = () => { if (spinning && map.current) m.rotateTo(m.getBearing() + 6, { duration: 6000, easing: (t) => t }); };
    m.on("moveend", () => spinning && turn());
    m.on("load", () => {
      m.addSource("segs", { type: "geojson", data: EMPTY });
      m.addSource("cols", { type: "geojson", data: EMPTY });
      m.addSource("route-dry", { type: "geojson", data: EMPTY });
      m.addSource("route-wet", { type: "geojson", data: EMPTY });
      m.addLayer({ id: "seg-glow", type: "line", source: "segs", paint: { "line-color": ["get", "color"], "line-width": 18, "line-blur": 14, "line-opacity": 0.55 } });
      m.addLayer({ id: "seg-line", type: "line", source: "segs", layout: { "line-cap": "round" }, paint: { "line-color": ["get", "color"], "line-width": 4 } });
      m.addLayer({ id: "seg-cols", type: "fill-extrusion", source: "cols", paint: { "fill-extrusion-color": ["get", "color"], "fill-extrusion-height": ["get", "h"], "fill-extrusion-opacity": 0.78 } });
      m.addLayer({ id: "route-dry-casing", type: "line", source: "route-dry", layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": "#0b0d0c", "line-width": 9 } });
      m.addLayer({ id: "route-dry", type: "line", source: "route-dry", layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": "#CBF34D", "line-width": 5 } });
      m.addLayer({ id: "route-wet", type: "line", source: "route-wet", layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": "#FF4D5E", "line-width": 6, "line-dasharray": [1, 1.2] } });
      const pick = (e) => onSelect && onSelect(e.features[0].properties.id);
      m.on("click", "seg-line", pick);
      m.on("click", "seg-cols", pick);
      setReady(true);
      // terrain is enabled after load so overlays work even where 3D terrain is slow to initialise
      try { m.setTerrain({ source: "dem", exaggeration: EXAG }); } catch { /* 2D fallback */ }
      setTimeout(turn, 1200);
    });
    const sample = () => {
      const pts = [];
      for (let i = 0; i < 26; i++) for (let j = 0; j < 26; j++) {
        const e = m.queryTerrainElevation([69.05 + (0.11 * i) / 25, 54.865 + (0.05 * j) / 25]);
        if (e) pts.push(e / EXAG);
      }
      if (pts.length < 200) return false;
      pts.sort((a, b) => a - b);
      const b = pts[Math.floor(pts.length * 0.02)];
      setBase(b);
      onReady && onReady({ riverBase: b, elev: (p) => { const e = m.queryTerrainElevation(p); return e == null ? null : e / EXAG; }, map: m });
      return true;
    };
    const trySample = () => { if (!sample()) setTimeout(trySample, 800); };
    m.once("idle", trySample);
    return () => { m.remove(); map.current = null; };
  }, []);

  // dams
  useEffect(() => {
    const m = map.current;
    if (!ready || !m || !state) return;
    const L = [], C = [];
    for (const s of state.segments) {
      const g = SEGMENTS[s.segment_id];
      if (!g) continue;
      L.push({ type: "Feature", properties: { id: s.segment_id, color: SEV[s.level] }, geometry: { type: "LineString", coordinates: g.line } });
      const [x, y] = mid(g.line), d = 0.0011, e = 0.00065;
      C.push({ type: "Feature", properties: { id: s.segment_id, color: SEV[s.level], h: 60 + s.risk * 900 }, geometry: { type: "Polygon", coordinates: [[[x - d, y - e], [x + d, y - e], [x + d, y + e], [x - d, y + e], [x - d, y - e]]] } });
    }
    const apply = () => {
      m.getSource("segs")?.setData({ type: "FeatureCollection", features: L });
      m.getSource("cols")?.setData({ type: "FeatureCollection", features: C });
    };
    apply();
    const t1 = setTimeout(apply, 700), t2 = setTimeout(apply, 2500);
    return () => { clearTimeout(t1); clearTimeout(t2); };
  }, [ready, state]);

  // markers: dam tags, stations, SOS, units, shelters
  useEffect(() => {
    const m = map.current;
    if (!ready || !m) return;
    marks.current.forEach((x) => x.remove());
    marks.current = [];
    const add = (el, ll, opt = {}) => marks.current.push(new maplibregl.Marker({ element: el, ...opt }).setLngLat(ll).addTo(m));
    if (state) for (const s of state.segments) {
      const g = SEGMENTS[s.segment_id];
      if (!g) continue;
      const el = document.createElement("button");
      el.className = "map-tag" + (selected === s.segment_id ? " is-sel" : "");
      el.innerHTML = `<i style="background:${SEV[s.level]}"></i><span>${g.area}</span><b>${Math.round(s.risk * 100)}%</b>`;
      el.onclick = () => onSelect && onSelect(s.segment_id);
      add(el, mid(g.line), { anchor: "bottom", offset: [0, -14] });
    }
    if (!sos.length) for (const [id, st] of Object.entries(STATIONS)) {
      const el = document.createElement("div");
      el.className = "map-station " + st.kind;
      el.title = id;
      add(el, st.coord);
    }
    for (const s of sos) {
      const el = document.createElement("button");
      el.className = "map-sos" + (selectedSos === s.id ? " is-sel" : "") + (s.status !== "new" ? " is-taken" : "");
      el.style.setProperty("--c", prioColor(s.priority));
      el.innerHTML = `<span>SOS</span><b>${s.priority}</b>`;
      el.title = s.address || "";
      el.onclick = () => onSos && onSos(s.id);
      add(el, [s.lon, s.lat]);
    }
    for (const u of units) {
      if (u.lat == null) continue;
      const el = document.createElement("div");
      el.className = `map-unit ${u.service} ${u.status}`;
      el.innerHTML = `<b>${u.callsign}</b>`;
      add(el, [u.lon, u.lat]);
    }
    for (const sh of shelters) {
      const el = document.createElement("div");
      el.className = "map-shelter";
      el.title = sh.name;
      el.innerHTML = "<b>П</b>";
      add(el, [sh.lon, sh.lat]);
    }
  }, [ready, state, selected, sos, units, shelters, selectedSos]);

  // route
  useEffect(() => {
    const m = map.current;
    if (!ready || !m) return;
    const apply = () => {
      m.getSource("route-dry")?.setData(route ? lines(route.dry) : EMPTY);
      m.getSource("route-wet")?.setData(route ? lines(route.wet) : EMPTY);
    };
    apply();
    const fit = () => route && route.bounds && m.fitBounds(route.bounds, { padding: 160, pitch: 50, duration: 1200, maxZoom: 15 });
    fit();
    // re-apply after terrain/source reloads so the route is never dropped
    const t1 = setTimeout(apply, 700), t2 = setTimeout(apply, 2500), t3 = setTimeout(fit, 800);
    return () => { clearTimeout(t1); clearTimeout(t2); clearTimeout(t3); };
  }, [ready, route]);

  // flood
  useEffect(() => {
    const m = map.current;
    if (!ready || !m || base == null || waterLevel == null) return;
    const e = base + waterLevel;
    if (!m.getLayer("flood")) {
      try { m.addLayer({ id: "flood", type: "color-relief", source: "dem2", paint: { "color-relief-color": floodRamp(e), "color-relief-opacity": 0.9 } }, "seg-glow"); } catch { /* no color-relief */ }
    } else m.setPaintProperty("flood", "color-relief-color", floodRamp(e));
  }, [ready, base, waterLevel]);

  useEffect(() => {
    const m = map.current;
    const g = selected && SEGMENTS[selected];
    if (m && g) m.flyTo({ center: mid(g.line), zoom: 14.6, pitch: 66, duration: 1800 });
  }, [selected]);

  return <div ref={box} className={className} aria-label="3D-карта Петропавловска" />;
}
