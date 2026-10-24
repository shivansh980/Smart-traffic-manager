"""SumoRunner: one headless SUMO sim, its observations, and its frames (spec 4.3, 4.4, 5.2)."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

import sumolib
import traci
import traci.constants as tc

from core.types import Controller, LaneObs, TLSInfo

VARS = [tc.VAR_POSITION, tc.VAR_ANGLE, tc.VAR_TYPE, tc.VAR_SPEED, tc.VAR_CO2EMISSION,
        tc.VAR_WAITING_TIME, tc.VAR_LANE_ID, tc.VAR_LANEPOSITION]
HALT_SPEED = 0.1
EXPECTED_TLS = 9
KIND = {"bus": "b", "ambulance": "e"}
DT = 1.0


def _net_path(cfg: str) -> Path:
    net = ET.parse(cfg).getroot().find("./input/net-file").get("value")
    return Path(cfg).resolve().parent / net


def _signal(chars: str) -> str:
    if any(c in "Gg" for c in chars):
        return "G"
    return "y" if "y" in chars else "r"


class SumoRunner:
    def __init__(self, label: str, cfg: str, seed: int,
                 controller: Controller | None,
                 tripinfo: str | None = None):
        self.label, self.controller = label, controller
        extra = ["--tripinfo-output", tripinfo, "--tripinfo-output.write-unfinished", "true",
                 "--device.emissions.probability", "1"] if tripinfo else []
        traci.start(["sumo", "-c", cfg, "--seed", str(seed)] + extra, label=label)
        self.conn = traci.getConnection(label)

        net = sumolib.net.readNet(str(_net_path(cfg)))
        self.lane_len = {l.getID(): l.getLength() for e in net.getEdges() for l in e.getLanes()}

        self.tls: list[TLSInfo] = []
        for tls_id in self.conn.trafficlight.getIDList():
            links = [(l[0][0], l[0][1]) if l else ("", "") for l in self.conn.trafficlight.getControlledLinks(tls_id)]
            phases = self.conn.trafficlight.getAllProgramLogics(tls_id)[0].phases
            greens = list(dict.fromkeys(p.state for p in phases
                                        if any(c in "Gg" for c in p.state) and "y" not in p.state))
            if len(greens) >= 2:
                self.tls.append(TLSInfo(tls_id, links, greens, self.conn.trafficlight.getRedYellowGreenState(tls_id)))
        assert len(self.tls) == EXPECTED_TLS, f"expected {EXPECTED_TLS} controllable lights, got {len(self.tls)}"

        self.obs_lanes = {l for info in self.tls for pair in info.links for l in pair if l}
        # incoming lane -> signal indices, per light (for the "sig" frame field)
        self.lane_idx = {info.tls_id: {} for info in self.tls}
        for info in self.tls:
            for i, (a, _) in enumerate(info.links):
                if a:
                    self.lane_idx[info.tls_id].setdefault(a, []).append(i)
        # approaches (incoming edges) per light, for tls_wait
        self.approaches = {info.tls_id: {} for info in self.tls}
        for info in self.tls:
            for a, _ in info.links:
                if a:
                    self.approaches[info.tls_id].setdefault(a.rsplit("_", 1)[0], set()).add(a)

        for info in self.tls:
            self.conn.trafficlight.subscribe(info.tls_id, [tc.TL_RED_YELLOW_GREEN_STATE])
            if controller is not None:
                controller.register(info)
        self.shown = {info.tls_id: info.initial_state for info in self.tls}

        self.t = 0.0
        self.arrived = 0
        self.halt_vs = 0.0
        self.co2_kg = 0.0
        self.idle_co2_kg = 0.0
        self.teleports = 0
        self.tls_wait_sum = {info.tls_id: 0.0 for info in self.tls}
        self.steps = 0
        self.amb_n = 0
        self.amb_spawned: dict[str, float] = {}     # vid -> spawn time, while active
        self.amb_last_trip_s: Optional[float] = None

    def spawn_ambulance(self) -> None:
        self.amb_n += 1
        vid = f"amb{self.amb_n}"
        self.conn.vehicle.add(vid, "amb_route", typeID="ambulance", departLane="best", departSpeed="max")
        self.amb_spawned[vid] = self.t

    def step(self) -> dict:
        conn = self.conn
        conn.simulationStep()
        self.t = conn.simulation.getTime()
        for vid in conn.simulation.getDepartedIDList():
            conn.vehicle.subscribe(vid, VARS)
        res = conn.vehicle.getAllSubscriptionResults()

        self.arrived += conn.simulation.getArrivedNumber()
        self.teleports += conn.simulation.getStartingTeleportNumber()
        for vid in conn.simulation.getArrivedIDList():
            if vid in self.amb_spawned:
                self.amb_last_trip_s = self.t - self.amb_spawned.pop(vid)

        lanes: dict[str, LaneObs] = {l: LaneObs() for l in self.obs_lanes}
        veh, halted_n, co2, idle_co2, max_wait = [], 0, 0.0, 0.0, 0.0
        for vid, v in res.items():
            x, y = v[tc.VAR_POSITION]
            vtype = v[tc.VAR_TYPE]
            halted = v[tc.VAR_SPEED] < HALT_SPEED
            rate = v[tc.VAR_CO2EMISSION]
            wait = v[tc.VAR_WAITING_TIME]
            co2 += rate
            max_wait = max(max_wait, wait)
            if halted:
                halted_n += 1
                idle_co2 += rate
            veh.append([vid, round(x, 1), round(y, 1), round(v[tc.VAR_ANGLE], 1), KIND.get(vtype, "c"), int(halted)])

            lane = v[tc.VAR_LANE_ID]
            o = lanes.get(lane)
            if o is None:
                continue
            if halted:
                o.halting += 1
                o.co2_mg_s += rate
                if vtype == "bus":
                    o.buses += 1
            o.max_wait_s = max(o.max_wait_s, wait)
            if vtype == "ambulance":
                d = self.lane_len[lane] - v[tc.VAR_LANEPOSITION]
                if o.emergency_dist_m is None or d < o.emergency_dist_m:
                    o.emergency_dist_m = d

        self.halt_vs += halted_n * DT
        self.co2_kg += co2 * DT / 1e6
        self.idle_co2_kg += idle_co2 * DT / 1e6
        self.steps += 1

        tl_res = conn.trafficlight.getAllSubscriptionResults()
        sig = {}
        for info in self.tls:
            state = tl_res[info.tls_id][tc.TL_RED_YELLOW_GREEN_STATE]
            for lane, idx in self.lane_idx[info.tls_id].items():
                sig[lane] = _signal("".join(state[i] for i in idx))
            appr = self.approaches[info.tls_id]
            self.tls_wait_sum[info.tls_id] += sum(lanes[l].halting for ls in appr.values() for l in ls) / len(appr)

        if self.controller is not None:
            for info in self.tls:
                s = self.controller.step(info.tls_id, self.t, lanes)
                if s != self.shown[info.tls_id]:
                    conn.trafficlight.setRedYellowGreenState(info.tls_id, s)
                    self.shown[info.tls_id] = s

        running = len(res)
        amb_active = bool(self.amb_spawned)
        m = {
            "t": self.t,
            "running": running,
            "arrived": self.arrived,
            "avg_delay_s": round(self.halt_vs / max(1, self.arrived + running), 2),
            "queue": halted_n,
            "co2_kg": round(self.co2_kg, 3),
            "idle_co2_kg": round(self.idle_co2_kg, 3),
            "max_wait_s": max_wait,
            "teleports": self.teleports,
            "amb_active": amb_active,
            "amb_elapsed_s": self.t - min(self.amb_spawned.values()) if amb_active else None,
            "amb_last_trip_s": self.amb_last_trip_s,
            "tls_wait": {k: round(v / self.steps, 2) for k, v in self.tls_wait_sum.items()},
        }
        return {"veh": veh, "sig": sig, "m": m}

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass
