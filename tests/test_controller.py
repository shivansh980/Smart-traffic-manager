from __future__ import annotations

import random

from core.controller import ALL_RED, MAX_GREEN, MIN_GREEN, YELLOW, WeightedMaxPressure
from core.types import LaneObs, TLSInfo, Weights

NS, EW = "GGrr", "rrGG"
INFO = TLSInfo(
    tls_id="X",
    links=[("n_in", "s_out"), ("s_in", "n_out"), ("e_in", "w_out"), ("w_in", "e_out")],
    green_states=[NS, EW],
    initial_state=NS,
)


def make(weights: Weights | None = None) -> WeightedMaxPressure:
    c = WeightedMaxPressure(weights or Weights())
    c.register(INFO)
    return c


def run(c, lanes_at, t0=0, t1=30):
    return [c.step("X", t, lanes_at(t)) for t in range(t0, t1)]


def test_heavy_queue_wins():
    states = run(make(), lambda t: {"e_in": LaneObs(halting=10)})
    assert states[MIN_GREEN] == "yyrr"
    assert states[MIN_GREEN + YELLOW] == "rrrr"
    assert states[MIN_GREEN + YELLOW + ALL_RED] == EW


def test_min_green_respected():
    states = run(make(), lambda t: {"e_in": LaneObs(halting=50)})
    assert all(s == NS for s in states[:MIN_GREEN])


def test_hysteresis_keeps_green_on_small_gap():
    states = run(make(), lambda t: {"e_in": LaneObs(halting=2), "n_in": LaneObs(halting=1)})
    assert all(s == NS for s in states)


def test_yellow_and_all_red_precede_every_change():
    rng = random.Random(0)
    c = make(Weights(flow=1, climate=1, transit=1, fairness=1))
    lanes = lambda t: {l: LaneObs(halting=rng.randint(0, 12), co2_mg_s=rng.uniform(0, 5000),
                                  buses=rng.randint(0, 1), max_wait_s=rng.uniform(0, 120))
                       for l in ("n_in", "s_in", "e_in", "w_in")}
    states = run(c, lanes, 0, 2000)
    changes = 0
    for i in range(1, len(states)):
        prev, cur = states[i - 1], states[i]
        if prev in (NS, EW) and cur != prev:
            changes += 1
            assert cur == "yyrr" if prev == NS else cur == "rryy"
            assert states[i:i + YELLOW] == [cur] * YELLOW
            assert states[i + YELLOW:i + YELLOW + ALL_RED] == ["rrrr"] * ALL_RED
            assert states[i + YELLOW + ALL_RED] in (NS, EW)
    assert changes > 10


def test_preemption_ignores_min_green_but_not_yellow():
    amb = lambda t: {"e_in": LaneObs(emergency_dist_m=100.0)} if t >= 2 else {}
    states = run(make(), amb, 0, 10)
    assert states[:2] == [NS, NS]
    assert states[2:2 + YELLOW] == ["yyrr"] * YELLOW
    assert states[2 + YELLOW] == "rrrr"
    assert states[2 + YELLOW + ALL_RED] == EW


def test_preemption_off_means_no_early_switch():
    amb = lambda t: {"e_in": LaneObs(emergency_dist_m=100.0)}
    states = run(make(Weights(preempt=False)), amb, 0, MIN_GREEN)
    assert all(s == NS for s in states)


def test_preemption_out_of_range_is_ignored():
    amb = lambda t: {"e_in": LaneObs(emergency_dist_m=400.0)}
    states = run(make(), amb, 0, MIN_GREEN)
    assert all(s == NS for s in states)


def test_preemption_holds_green_past_max_green():
    lanes = lambda t: {"n_in": LaneObs(emergency_dist_m=50.0), "e_in": LaneObs(halting=30)}
    states = run(make(), lanes, 0, MAX_GREEN + 10)
    assert all(s == NS for s in states)


def test_max_green_rotates():
    lanes = lambda t: {"n_in": LaneObs(halting=20), "e_in": LaneObs(halting=1)}
    states = run(make(), lanes, 0, MAX_GREEN + 10)
    assert all(s == NS for s in states[:MAX_GREEN])
    assert states[MAX_GREEN] == "yyrr"
    assert states[MAX_GREEN + YELLOW + ALL_RED] == EW


def test_weights_are_live():
    c = make()
    lanes = lambda t: {"n_in": LaneObs(halting=3), "e_in": LaneObs(halting=1, buses=1)}
    assert run(c, lanes, 0, 20)[-1] == NS        # flow only: NS has the bigger queue
    c.weights.transit = 2.0                       # city raises transit priority
    states = run(c, lanes, 20, 40)
    assert EW in states


def test_out_lane_backpressure():
    # Same in-queue, but EW's downstream lane is full: pressure favours NS.
    c = make()
    lanes = lambda t: {"n_in": LaneObs(halting=5), "e_in": LaneObs(halting=5), "w_out": LaneObs(halting=10)}
    assert c.score("X", NS, lanes(0)) > c.score("X", EW, lanes(0))


def test_climate_protects_moving_platoon():
    # NS has a platoon rolling toward the stop line; EW has a small queue. Flow alone would switch,
    # the climate weight keeps the platoon moving.
    lanes = lambda t: {"n_in": LaneObs(approaching=6), "e_in": LaneObs(halting=4)}
    assert run(make(Weights(climate=0)), lanes, 0, 20)[MIN_GREEN] == "yyrr"
    assert all(s == NS for s in run(make(Weights(climate=2.5)), lanes, 0, 20))
