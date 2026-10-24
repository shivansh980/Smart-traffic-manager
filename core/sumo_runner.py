"""SumoRunner: one headless SUMO sim, its observations, and its frames (spec 4.3, 4.4, 5.2)."""
from __future__ import annotations

import json
import random
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

import sumolib
import traci
import traci.constants as tc

from core.types import Controller, LaneObs, TLSInfo

VARS = [tc.VAR_POSITION, tc.VAR_ANGLE, tc.VAR_TYPE, tc.VAR_SPEED, tc.VAR_CO2EMISSION,
        tc.VAR_WAITING_TIME, tc.VAR_LANE_ID, tc.VAR_LANEPOSITION,
        tc.VAR_NOXEMISSION, tc.VAR_PMXEMISSION, tc.VAR_FUELCONSUMPTION]
HALT_SPEED = 0.1
KIND = {"bus": "b", "ambulance": "e", "crash": "x"}
DT = 1.0
HEAT_EVERY = 5          # steps between heatmap updates in the frame
HEAT_ALPHA = 0.05       # EMA weight per step (~20 s memory)
FUEL_MG_PER_L = 745_000  # gasoline density

# Signal strategies: which SUMO program runs when no controller is attached (built by scenario/build.py)
PROGRAMS = {"fixed": "0", "actuated": "actuated", "greenwave": "greenwave"}


def _cfg_dir(cfg: str) -> Path:
    return Path(cfg).resolve().parent


def _net_path(cfg: str) -> Path:
    net = ET.parse(cfg).getroot().find("./input/net-file").get("value")
    return _cfg_dir(cfg) / net


def _signal(chars: str) -> str:
    if any(c in "Gg" for c in chars):
        return "G"
    return "y" if "y" in chars else "r"


class SumoRunner:
    def __init__(self, label: str, cfg: str, seed: int,
                 controller: Controller | None,
                 tripinfo: str | None = None,
                 program: str = "0"):
        """program: SUMO program for controller-less runs ("0" fixed-time, "actuated", "greenwave")."""
        self.label, self.controller, self.seed = label, controller, seed
        extra = ["--tripinfo-output", tripinfo, "--tripinfo-output.write-unfinished", "true",
                 "--device.emissions.probability", "1"] if tripinfo else []
        traci.start(["sumo", "-c", cfg, "--seed", str(seed)] + extra, label=label)
        self.conn = traci.getConnection(label)
        meta_path = _cfg_dir(cfg) / "meta.json"
        self.meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}

        net = sumolib.net.readNet(str(_net_path(cfg)))
        self.lane_len = {l.getID(): l.getLength() for e in net.getEdges() for l in e.getLanes()}
        self.edge_len = {e.getID(): e.getLength() for e in net.getEdges()}
        self.edge_name = {e.getID(): e.getName() or e.getID() for e in net.getEdges()}

        self.tls: list[TLSInfo] = []
        for tls_id in self.conn.trafficlight.getIDList():
            logics = {l.programID: l for l in self.conn.trafficlight.getAllProgramLogics(tls_id)}
            base = logics.get("0") or next(iter(logics.values()))
            greens = list(dict.fromkeys(p.state for p in base.phases
                                        if any(c in "Gg" for c in p.state) and "y" not in p.state))
            # every light runs the chosen program; the adaptive controller then overrides it state by state
            want = "0" if controller is not None else program
            if want in logics:
                self.conn.trafficlight.setProgram(tls_id, want)
            if len(greens) >= 2:
                links = [(l[0][0], l[0][1]) if l else ("", "")
                         for l in self.conn.trafficlight.getControlledLinks(tls_id)]
                self.tls.append(TLSInfo(tls_id, links, greens, self.conn.trafficlight.getRedYellowGreenState(tls_id)))
        expected = self.meta.get("expected_tls")
        assert expected is None or len(self.tls) == expected, f"expected {expected} controllable lights, got {len(self.tls)}"

        self.obs_lanes = {l for info in self.tls for pair in info.links for l in pair if l}
        self.links = {info.tls_id: info.links for info in self.tls}
        # incoming lane -> signal indices, per light (for the "sig" frame field)
        self.lane_idx = {info.tls_id: {} for info in self.tls}
        for info in self.tls:
            for i, (a, _) in enumerate(info.links):
                if a:
                    self.lane_idx[info.tls_id].setdefault(a, []).append(i)
        # approaches (incoming edges) per light, for tls_wait and the inspector
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
        self.tl_state = dict(self.shown)

        self.t = 0.0
        self.arrived = 0
        self.halt_vs = 0.0
        self.veh_s = 0.0
        self.co2_kg = 0.0
        self.idle_co2_kg = 0.0
        self.fuel_l = 0.0
        self.nox_g = 0.0
        self.pm_g = 0.0
        self.stops = 0
        self.teleports = 0
        self.tls_wait_sum = {info.tls_id: 0.0 for info in self.tls}
        self.steps = 0
        self.lanes: dict[str, LaneObs] = {}
        self.heat: dict[str, float] = {}
        self.was_halted: dict[str, bool] = {}
        self.depart: dict[str, float] = {}
        self.bus_trips: list[float] = []
        self.amb_n = 0
        self.amb_spawned: dict[str, float] = {}     # vid -> spawn time, while active
        self.amb_last_trip_s: Optional[float] = None
        self.amb_trips: list[float] = []            # every completed ambulance trip, in order
        self.events_n = 0
        self.routes: set[str] = set()

    # ------------------------------------------------------------------ events (same ids and times in every sim)

    def spawn_ambulance(self) -> None:
        self.amb_n += 1
        vid = f"amb{self.amb_n}"
        self.conn.vehicle.add(vid, "amb_route", typeID="ambulance", departLane="best", departSpeed="max")
        self.amb_spawned[vid] = self.t

    def surge(self) -> int:
        """Crowd lets out: n cars from the venue's streets to far exits, spread over over_s seconds."""
        spec = self.meta.get("surge")
        if not spec:
            return 0
        self.events_n += 1
        rng = random.Random(1000 + self.events_n)
        added = 0
        for i in range(spec["n"]):
            frm, to = rng.choice(spec["from"]), rng.choice(spec["to"])
            rid = self._route(frm, to)
            if rid is None:
                continue
            depart = self.t + 1 + rng.uniform(0, spec["over_s"])
            self.conn.vehicle.add(f"surge{self.events_n}_{i}", rid, typeID="car", depart=f"{depart:.0f}",
                                  departLane="best", departPos="random", departSpeed="0")
            added += 1
        return added

    def crash(self) -> None:
        """Stalled cars block lanes on one block for spec duration seconds."""
        spec = self.meta.get("crash")
        if not spec:
            return
        self.events_n += 1
        rid = self._route(spec["edge"], spec["edge"])
        for lane in spec["lanes"]:
            vid = f"crash{self.events_n}_{lane}"
            self.conn.vehicle.add(vid, rid, typeID="crash", departLane=str(lane), departPos=str(spec["pos"]),
                                  departSpeed="0")
            self.conn.vehicle.setStop(vid, spec["edge"], pos=spec["pos"] + 5, laneIndex=lane,
                                      duration=spec["duration"])

    def _route(self, frm: str, to: str) -> Optional[str]:
        rid = f"r_{frm}_{to}"
        if rid not in self.routes:
            edges = [frm] if frm == to else list(self.conn.simulation.findRoute(frm, to).edges)
            if not edges:
                return None
            self.conn.route.add(rid, edges)
            self.routes.add(rid)
        return rid

    # ------------------------------------------------------------------ stepping

    def step(self) -> dict:
        conn = self.conn
        conn.simulationStep()
        self.t = conn.simulation.getTime()
        for vid in conn.simulation.getDepartedIDList():
            conn.vehicle.subscribe(vid, VARS)
            self.depart[vid] = self.t
        res = conn.vehicle.getAllSubscriptionResults()

        self.arrived += conn.simulation.getArrivedNumber()
        self.teleports += conn.simulation.getStartingTeleportNumber()
        for vid in conn.simulation.getArrivedIDList():
            if vid in self.amb_spawned:
                self.amb_last_trip_s = self.t - self.amb_spawned.pop(vid)
                self.amb_trips.append(self.amb_last_trip_s)
            if vid.startswith("bus") and vid in self.depart:
                self.bus_trips.append(self.t - self.depart[vid])
            self.depart.pop(vid, None)
            self.was_halted.pop(vid, None)

        lanes: dict[str, LaneObs] = {l: LaneObs() for l in self.obs_lanes}
        edge_co2: dict[str, float] = {}
        veh, halted_n, co2, idle_co2, max_wait = [], 0, 0.0, 0.0, 0.0
        fuel = nox = pm = 0.0
        for vid, v in res.items():
            x, y = v[tc.VAR_POSITION]
            vtype = v[tc.VAR_TYPE]
            halted = v[tc.VAR_SPEED] < HALT_SPEED
            rate = v[tc.VAR_CO2EMISSION]
            wait = v[tc.VAR_WAITING_TIME]
            co2 += rate
            fuel += v[tc.VAR_FUELCONSUMPTION]
            nox += v[tc.VAR_NOXEMISSION]
            pm += v[tc.VAR_PMXEMISSION]
            if vtype != "crash":
                max_wait = max(max_wait, wait)
                if halted:
                    halted_n += 1
                    idle_co2 += rate
                    if not self.was_halted.get(vid):
                        self.stops += 1
                self.was_halted[vid] = halted
            veh.append([vid, round(x, 1), round(y, 1), round(v[tc.VAR_ANGLE], 1), KIND.get(vtype, "c"), int(halted)])

            lane = v[tc.VAR_LANE_ID]
            if not lane.startswith(":"):
                edge = lane.rsplit("_", 1)[0]
                edge_co2[edge] = edge_co2.get(edge, 0.0) + rate
            if vtype == "ambulance" and self.controller is not None:
                self._mark_corridor(vid, lanes)
            o = lanes.get(lane)
            if o is None:
                continue
            if halted:
                o.halting += 1
                o.co2_mg_s += rate
                if vtype == "bus":
                    o.buses += 1
            else:
                o.approaching += 1
            o.max_wait_s = max(o.max_wait_s, wait)
            if vtype == "ambulance":
                d = self.lane_len[lane] - v[tc.VAR_LANEPOSITION]
                if o.emergency_dist_m is None or d < o.emergency_dist_m:
                    o.emergency_dist_m = d

        running = sum(1 for v in res.values() if v[tc.VAR_TYPE] != "crash")
        self.halt_vs += halted_n * DT
        self.veh_s += running * DT
        self.co2_kg += co2 * DT / 1e6
        self.idle_co2_kg += idle_co2 * DT / 1e6
        self.fuel_l += fuel * DT / FUEL_MG_PER_L
        self.nox_g += nox * DT / 1e3
        self.pm_g += pm * DT / 1e3
        self.steps += 1
        self.lanes = lanes
        for e in set(self.heat) | set(edge_co2):   # g/s per 100 m, smoothed
            now = edge_co2.get(e, 0.0) / 1000 / max(self.edge_len.get(e, 100.0), 1.0) * 100
            self.heat[e] = self.heat.get(e, 0.0) * (1 - HEAT_ALPHA) + now * HEAT_ALPHA

        tl_res = conn.trafficlight.getAllSubscriptionResults()
        sig = {}
        for info in self.tls:
            state = tl_res[info.tls_id][tc.TL_RED_YELLOW_GREEN_STATE]
            self.tl_state[info.tls_id] = state
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
            # additions after the freeze (cumulative): rolling windows and the health/money hooks
            "halt_vs": round(self.halt_vs, 1),
            "veh_s": round(self.veh_s, 1),
            "stops": self.stops,
            "fuel_l": round(self.fuel_l, 3),
            "nox_g": round(self.nox_g, 2),
            "pm_g": round(self.pm_g, 3),
            "bus_trips": len(self.bus_trips),
            "bus_avg_trip_s": round(sum(self.bus_trips) / len(self.bus_trips), 1) if self.bus_trips else None,
        }
        frame = {"veh": veh, "sig": sig, "m": m}
        if self.steps % HEAT_EVERY == 0:
            frame["heat"] = {e: round(h, 2) for e, h in self.heat.items() if h >= 0.01}
        return frame

    # ------------------------------------------------------------------ inspector

    def inspect(self, tls_id: str) -> Optional[dict]:
        """Why is this light showing what it shows? Approach queues plus, for the adaptive controller, its scores."""
        info = next((i for i in self.tls if i.tls_id == tls_id), None)
        if info is None:
            return None
        state = self.tl_state.get(tls_id, "")
        approaches = []
        for edge, lanes in sorted(self.approaches[tls_id].items()):
            obs = [self.lanes.get(l, LaneObs()) for l in lanes]
            idx = [i for l in lanes for i in self.lane_idx[tls_id].get(l, [])]
            approaches.append({
                "edge": edge, "name": self.edge_name.get(edge, edge),
                "queue": sum(o.halting for o in obs), "moving": sum(o.approaching for o in obs),
                "buses": sum(o.buses for o in obs), "max_wait_s": round(max((o.max_wait_s for o in obs), default=0)),
                "ambulance_m": min((o.emergency_dist_m for o in obs if o.emergency_dist_m is not None), default=None),
                "signal": _signal("".join(state[i] for i in idx)) if idx else "r",
            })
        out = {"tls": tls_id, "state": state, "approaches": approaches}
        if self.controller is not None and hasattr(self.controller, "explain"):
            out["controller"] = self.controller.explain(tls_id, self.lanes, self.edge_name)
        else:
            out["program"] = self.conn.trafficlight.getProgram(tls_id)
            out["next_switch_s"] = round(self.conn.trafficlight.getNextSwitch(tls_id) - self.t, 1)
        return out

    def _mark_corridor(self, vid: str, lanes: dict[str, LaneObs]) -> None:
        """Give every light ahead on the ambulance's route its distance to that stop line, so lights
        can clear their queues before it arrives rather than only the one it is approaching."""
        for tls_id, idx, dist, _ in self.conn.vehicle.getNextTLS(vid):
            links = self.links.get(tls_id)
            if links is None:
                continue
            o = lanes.get(links[idx][0])
            if o is not None and (o.emergency_dist_m is None or dist < o.emergency_dist_m):
                o.emergency_dist_m = dist

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass
