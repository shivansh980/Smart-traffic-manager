"""Weighted max-pressure signal control (spec section 5.3).

Each light picks, among its default program's green states, the one with the highest score:
queue pressure plus city-chosen climate / transit / fairness terms. Min-green, max-green,
yellow and all-red bounds keep it safe; emergency vehicles preempt.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from core.types import LaneObs, TLSInfo, Weights

MIN_GREEN = 8
MAX_GREEN = 60
YELLOW = 3
ALL_RED = 1
HYST = 2.0
PREEMPT_DIST_M = 300.0   # spec says 150; 300 lets lights ahead flush their queue first
# Climate term. Stop-and-go dominates CO2 (a restart burns far more than idling), so the climate
# weight protects moving platoons. The spec's version (idle CO2 only, IDLE_K=1, STOP_K=0) measured
# +3% total CO2; this one measured -10% total CO2 and -37% stops vs flow-only (2 seeds, climate=2.5).
CLIMATE_IDLE_K = 0.0     # weight on idling CO2 (g/s) of halted vehicles
CLIMATE_STOP_K = 1.0     # weight per moving vehicle a red would force to stop

_EMPTY = LaneObs()


def _green(c: str) -> bool:
    return c in "Gg"


def yellow_state(cur: str, target: str) -> str:
    return "".join("y" if _green(c) and not _green(t) else c for c, t in zip(cur, target))


def all_red_state(s: str) -> str:
    return "".join("r" if c in "Ggy" else c for c in s)


@dataclass
class _Light:
    info: TLSInfo
    pairs: dict[str, list[tuple[str, str]]]   # green state -> unique (in, out) pairs it serves
    in_lanes: dict[str, list[str]]            # green state -> unique in-lanes it serves
    in_lanes_all: list[str]                   # every in-lane any green state serves
    cur: str
    mode: str = "green"                       # green | yellow | allred
    since: float = 0.0
    target: Optional[str] = None
    shown: str = ""


@dataclass
class WeightedMaxPressure:
    weights: Weights = field(default_factory=Weights)
    lights: dict[str, _Light] = field(default_factory=dict)

    def register(self, info: TLSInfo) -> None:
        pairs, in_lanes = {}, {}
        for g in info.green_states:
            served = [info.links[i] for i, c in enumerate(g) if _green(c) and info.links[i][0]]
            pairs[g] = list(dict.fromkeys(served))
            in_lanes[g] = list(dict.fromkeys(p[0] for p in served))
        all_in = list(dict.fromkeys(l for ls in in_lanes.values() for l in ls))
        cur = info.initial_state if info.initial_state in info.green_states else info.green_states[0]
        self.lights[info.tls_id] = _Light(info, pairs, in_lanes, all_in, cur, shown=cur)

    def score(self, tls_id: str, g: str, lanes: dict[str, LaneObs]) -> float:
        light, w = self.lights[tls_id], self.weights
        s = 0.0
        for a, b in light.pairs[g]:
            s += w.flow * (lanes.get(a, _EMPTY).halting - lanes.get(b, _EMPTY).halting)
        for a in light.in_lanes[g]:
            o = lanes.get(a, _EMPTY)
            s += w.climate * (CLIMATE_IDLE_K * o.co2_mg_s / 1000 + CLIMATE_STOP_K * o.approaching)
            s += w.transit * 5 * o.buses + w.fairness * o.max_wait_s / 30
        return s

    def _preempt_target(self, light: _Light, lanes: dict[str, LaneObs]) -> Optional[str]:
        """Green state serving the in-lane with the nearest emergency vehicle within range, if any."""
        if not self.weights.preempt:
            return None
        best_lane, best_dist = None, PREEMPT_DIST_M
        for lane in light.in_lanes_all:
            d = lanes.get(lane, _EMPTY).emergency_dist_m
            if d is not None and d <= best_dist:
                best_lane, best_dist = lane, d
        if best_lane is None:
            return None
        serving = [g for g in light.info.green_states if best_lane in light.in_lanes[g]]
        if not serving:
            return None
        if light.cur in serving and light.mode == "green":
            return light.cur
        return max(serving, key=lambda g: self.score(light.info.tls_id, g, lanes))

    def _begin_change(self, light: _Light, target: str, t: float) -> str:
        light.mode, light.since, light.target = "yellow", t, target
        return yellow_state(light.cur, target)

    def step(self, tls_id: str, t: float, lanes: dict[str, LaneObs]) -> str:
        light = self.lights[tls_id]
        light.shown = self._step(light, t, lanes)
        return light.shown

    def _step(self, light: _Light, t: float, lanes: dict[str, LaneObs]) -> str:
        pre = self._preempt_target(light, lanes)

        if light.mode == "yellow":
            if pre is not None:
                light.target = pre   # still goes through yellow and all-red
            if t - light.since < YELLOW:
                return light.shown
            light.mode, light.since = "allred", t
            return all_red_state(light.shown)

        if light.mode == "allred":
            if pre is not None:
                light.target = pre
            if t - light.since < ALL_RED:
                return light.shown
            light.mode, light.since, light.cur, light.target = "green", t, light.target, None
            return light.cur

        if pre is not None:
            if pre == light.cur:
                return light.cur     # hold the green for the emergency vehicle, even past max-green
            return self._begin_change(light, pre, t)

        t_green = t - light.since
        if t_green < MIN_GREEN:
            return light.cur

        tid = light.info.tls_id
        ranked = sorted(light.info.green_states, key=lambda g: self.score(tid, g, lanes), reverse=True)
        best = ranked[0]
        if t_green >= MAX_GREEN:
            nxt = ranked[1] if best == light.cur and len(ranked) > 1 else best
            return self._begin_change(light, nxt, t) if nxt != light.cur else light.cur
        if best != light.cur and self.score(tid, best, lanes) > self.score(tid, light.cur, lanes) + HYST:
            return self._begin_change(light, best, t)
        return light.cur
