#!/usr/bin/env python3
"""ARLAN SKY MIRROR station firmware (Raspberry Pi + u-blox).

Reads NMEA GSV sentences (satellite elevation, azimuth, SNR) from the GNSS receiver,
logs them to daily CSV files, and every `process_every_min` minutes runs GNSS-IR on the
last `window_hours` of data and sends the result to the ARLAN API.
If the network is down, results wait in an on-disk queue and are re-sent later.

Usage:
    python3 station.py --config config.json            # real receiver
    python3 station.py --config config.json --replay log.csv   # re-process a log
    python3 station.py --config config.json --simulate # no hardware, synthetic data
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import gnssir

log = logging.getLogger("arlan.gnss")


# ---------------------------------------------------------------- NMEA parsing
def nmea_checksum_ok(line: str) -> bool:
    if not line.startswith("$") or "*" not in line:
        return False
    body, _, cs = line[1:].partition("*")
    calc = 0
    for ch in body:
        calc ^= ord(ch)
    try:
        return calc == int(cs[:2], 16)
    except ValueError:
        return False


def parse_gsv(line: str, t: float) -> list[gnssir.Obs]:
    """$GPGSV,3,1,11,03,03,111,00,04,15,270,00,06,01,010,00,13,06,292,00*74"""
    line = line.strip()
    if not nmea_checksum_ok(line):
        return []
    fields = line[1:].split("*")[0].split(",")
    tag = fields[0]
    if len(tag) < 5 or tag[2:] != "GSV":
        return []
    system = gnssir.TALKER_TO_SYSTEM.get(tag[:2])
    if system is None:
        return []
    sats = fields[4:]
    # NMEA 4.10+ appends a signal ID: groups of 4 plus one trailing field
    if len(sats) % 4 == 1:
        sats = sats[:-1]
    out = []
    for i in range(0, len(sats) - 3, 4):
        prn, el, az, snr = sats[i:i + 4]
        if not (prn and el and az and snr):
            continue  # satellite not tracked: no SNR
        try:
            out.append(gnssir.Obs(t, system, int(prn), float(el), float(az), float(snr)))
        except ValueError:
            continue
    return out


# ---------------------------------------------------------------- storage
class ObsLog:
    def __init__(self, data_dir: Path, keep_hours: float):
        self.dir = data_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.buf: deque[gnssir.Obs] = deque()
        self.keep_s = keep_hours * 3600
        self.lock = threading.Lock()

    def add(self, obs: list[gnssir.Obs]):
        if not obs:
            return
        day = datetime.fromtimestamp(obs[0].t, timezone.utc).strftime("%Y%m%d")
        path = self.dir / f"snr_{day}.csv"
        new = not path.exists()
        with path.open("a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["t", "system", "prn", "elev", "azim", "snr"])
            for o in obs:
                w.writerow([f"{o.t:.0f}", o.system, o.prn, o.elev, o.azim, o.snr])
        with self.lock:
            self.buf.extend(obs)
            cutoff = obs[-1].t - self.keep_s
            while self.buf and self.buf[0].t < cutoff:
                self.buf.popleft()

    def window(self, hours: float) -> list[gnssir.Obs]:
        with self.lock:
            if not self.buf:
                return []
            cutoff = self.buf[-1].t - hours * 3600
            return [o for o in self.buf if o.t >= cutoff]


def load_csv(path: Path) -> list[gnssir.Obs]:
    out = []
    with path.open() as f:
        for r in csv.DictReader(f):
            out.append(gnssir.Obs(float(r["t"]), r["system"], int(r["prn"]),
                                  float(r["elev"]), float(r["azim"]), float(r["snr"])))
    return out


# ---------------------------------------------------------------- uplink
class Uplink:
    """POST JSON to the API; on failure keep messages in a queue file."""

    def __init__(self, cfg: dict, data_dir: Path):
        self.url = cfg["api_url"].rstrip("/")
        self.key = cfg.get("api_key", "")
        self.queue = data_dir / "outbox.jsonl"

    def send(self, path: str, payload: dict) -> bool:
        import requests  # imported lazily so tests run without network libs
        try:
            r = requests.post(self.url + path, json=payload, timeout=15,
                              headers={"X-API-Key": self.key})
            r.raise_for_status()
            return True
        except Exception as e:  # noqa: BLE001 - any network error -> queue
            log.warning("uplink failed (%s), queued", e)
            with self.queue.open("a") as f:
                f.write(json.dumps({"path": path, "payload": payload}) + "\n")
            return False

    def flush(self):
        if not self.queue.exists():
            return
        lines = self.queue.read_text().splitlines()
        self.queue.unlink()
        for ln in lines:
            m = json.loads(ln)
            if not self.send(m["path"], m["payload"]):
                break


# ---------------------------------------------------------------- processing
def build_payload(cfg: dict, res: dict) -> dict:
    mode = cfg.get("mode", "water")
    p = {
        "station_id": cfg["station_id"],
        "ts": datetime.fromtimestamp(res.get("t_mid", time.time()), timezone.utc).isoformat(),
        "mode": mode,
        "ok": res["ok"],
        "n_arcs": res.get("n_arcs", 0),
        "quality": res.get("quality", 0.0),
    }
    if res["ok"]:
        rh = res["reflector_height_m"]
        p["reflector_height_m"] = rh
        p["rh_std_m"] = res["rh_std_m"]
        if mode == "water" and cfg.get("antenna_elevation_m") is not None:
            p["water_level_m"] = round(gnssir.to_level(rh, cfg["antenna_elevation_m"]), 4)
        if mode == "snow" and cfg.get("snow_bare_height_m") is not None:
            p["snow_depth_m"] = round(gnssir.to_snow_depth(rh, cfg["snow_bare_height_m"]), 4)
    return p


def settings_from(cfg: dict) -> gnssir.Settings:
    s = gnssir.Settings()
    for k, v in cfg.get("gnssir", {}).items():
        if hasattr(s, k):
            setattr(s, k, v)
    if "azimuth_mask" in cfg:
        s.azimuth_mask = cfg["azimuth_mask"]
    return s


def cpu_temp() -> float | None:
    p = Path("/sys/class/thermal/thermal_zone0/temp")
    try:
        return int(p.read_text()) / 1000.0
    except Exception:  # noqa: BLE001
        return None


def process_once(cfg, store: ObsLog, up: Uplink | None):
    obs = store.window(cfg.get("window_hours", 6))
    res = gnssir.estimate(obs, settings_from(cfg))
    payload = build_payload(cfg, res)
    payload["device"] = {"cpu_temp_c": cpu_temp(), "n_obs": len(obs)}
    log.info("arcs=%s RH=%s m q=%s", res.get("n_arcs"), res.get("reflector_height_m"),
             res.get("quality"))
    if up:
        up.flush()
        up.send("/api/v1/ingest/gnss", payload)
    return payload


# ---------------------------------------------------------------- sources
def read_serial(cfg, store: ObsLog, stop: threading.Event):
    import serial  # pyserial
    port, baud = cfg.get("serial_port", "/dev/serial0"), cfg.get("baud", 9600)
    while not stop.is_set():
        try:
            with serial.Serial(port, baud, timeout=2) as ser:
                log.info("reading %s @ %s", port, baud)
                batch: list[gnssir.Obs] = []
                last_flush = time.time()
                while not stop.is_set():
                    raw = ser.readline().decode("ascii", errors="ignore")
                    if "GSV" in raw:
                        batch += parse_gsv(raw, time.time())
                    if time.time() - last_flush > 5:
                        store.add(batch)
                        batch, last_flush = [], time.time()
        except Exception as e:  # noqa: BLE001
            log.error("serial error: %s; retry in 10 s", e)
            time.sleep(10)


def simulate(cfg, store: ObsLog, hours: float = 6):
    import numpy as np
    rng = np.random.default_rng()
    rh = cfg.get("simulate_rh_m", 3.2)
    t0 = time.time() - hours * 3600
    sats = [("GPS", p) for p in (2, 5, 12, 15, 20, 25)] + [("GLONASS", 3), ("GALILEO", 7)]
    for i, (sysn, prn) in enumerate(sats):
        store.add(gnssir.simulate_arc(rh, sysn, prn, t0=t0 + i * 2400, rising=i % 2 == 0,
                                      azim=160 + 4 * i, rng=rng))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--replay", help="process a CSV log once and exit")
    ap.add_argument("--simulate", action="store_true", help="synthetic data, no receiver")
    ap.add_argument("--no-upload", action="store_true")
    a = ap.parse_args(argv)

    cfg = json.loads(Path(a.config).read_text())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    data_dir = Path(cfg.get("data_dir", "data"))
    store = ObsLog(data_dir, keep_hours=max(24, cfg.get("window_hours", 6)))
    up = None if a.no_upload else Uplink(cfg, data_dir)

    if a.replay:
        store.add(load_csv(Path(a.replay)))
        print(json.dumps(process_once(cfg, store, up), indent=2))
        return 0
    if a.simulate:
        simulate(cfg, store)
        print(json.dumps(process_once(cfg, store, up), indent=2))
        return 0

    stop = threading.Event()
    th = threading.Thread(target=read_serial, args=(cfg, store, stop), daemon=True)
    th.start()
    every = cfg.get("process_every_min", 60) * 60
    try:
        while True:
            time.sleep(every)
            process_once(cfg, store, up)
    except KeyboardInterrupt:
        stop.set()
    return 0


if __name__ == "__main__":
    sys.exit(main())
