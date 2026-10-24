"""Headless fixed-time vs adaptive comparison (spec 5.4).

    python compare.py --quick              # 1 seed, 900 s, for checkpoints
    python compare.py --seeds 1 2 3        # full 2400 s, the numbers for the slide
"""
from __future__ import annotations

import argparse
import csv
import statistics
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from core.controller import WeightedMaxPressure
from core.sumo_runner import SumoRunner
from core.types import Weights

ROOT = Path(__file__).resolve().parent
CFG = str(ROOT / "scenario" / "sim.sumocfg")
RESULTS = ROOT / "results"
AMB_TIMES = [700, 900, 1100, 1300, 1500]   # several rush-hour dispatches: one is a coin flip on fixed-time phase
AMB_TIMES_QUICK = [550, 700]

METRICS = [  # key, label, lower is better
    ("delay_s", "Avg delay / vehicle (s, waitingTime)", True),
    ("time_loss_s", "Avg time loss / vehicle (s)", True),
    ("stops", "Stops / vehicle", True),
    ("co2_kg", "Total CO₂ (kg)", True),
    ("idle_co2_kg", "Idling CO₂ (kg)", True),
    ("throughput", "Throughput (vehicles arrived)", False),
    ("teleports", "Teleports", True),
    ("amb_s", "Ambulance trip, mean of dispatches (s)", True),
]


def controllers() -> dict[str, object]:
    return {"fixed": None, "adaptive": WeightedMaxPressure(Weights())}


def run_one(name: str, ctrl, seed: int, end: int) -> dict:
    trip = RESULTS / f"tripinfo_{name}_s{seed}.xml"
    r = SumoRunner(f"{name}_s{seed}", CFG, seed, ctrl, tripinfo=str(trip))
    amb_times = AMB_TIMES if end >= AMB_TIMES[-1] + 300 else AMB_TIMES_QUICK
    m = {}
    while r.t < end:
        if r.t in amb_times:
            r.spawn_ambulance()
        m = r.step()["m"]
    trips_amb = list(r.amb_trips)
    r.close()

    trips = [t for t in ET.parse(trip).getroot().iter("tripinfo") if not t.get("id").startswith("amb")]
    n = max(1, len(trips))
    co2_mg = sum(float(t.find("emissions").get("CO2_abs")) for t in trips if t.find("emissions") is not None)
    return {
        "delay_s": sum(float(t.get("waitingTime")) for t in trips) / n,
        "time_loss_s": sum(float(t.get("timeLoss")) for t in trips) / n,
        "stops": sum(float(t.get("waitingCount")) for t in trips) / n,
        "co2_kg": co2_mg / 1e6,
        "idle_co2_kg": m["idle_co2_kg"],
        "throughput": m["arrived"],
        "teleports": m["teleports"],
        "amb_s": statistics.mean(trips_amb) if trips_amb else None,
        "amb_trips": trips_amb,
    }


def mean_std(xs: list) -> tuple[float | None, float]:
    xs = [x for x in xs if x is not None]
    if not xs:
        return None, 0.0
    return statistics.mean(xs), statistics.stdev(xs) if len(xs) > 1 else 0.0


def fmt(ms: tuple[float | None, float]) -> str:
    m, s = ms
    if m is None:
        return "n/a"
    return f"{m:.1f} ± {s:.1f}" if s else f"{m:.1f}"


def pct(a: float | None, b: float | None) -> str:
    if a is None or b is None or a == 0:
        return "n/a"
    return f"{(b - a) / a * 100:+.1f}%"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3])
    ap.add_argument("--quick", action="store_true", help="1 seed, 900 s")
    ap.add_argument("--end", type=int, default=2400)
    args = ap.parse_args()
    seeds, end = ([args.seeds[0]], 900) if args.quick else (args.seeds, args.end)
    RESULTS.mkdir(exist_ok=True)

    runs: dict[str, list[dict]] = {}
    for seed in seeds:
        for name, ctrl in controllers().items():
            t0 = time.time()
            res = run_one(name, ctrl, seed, end)
            runs.setdefault(name, []).append(res)
            print(f"seed {seed} {name:9s} {time.time() - t0:5.1f}s  "
                  + "  ".join(f"{k}={v:.1f}" if isinstance(v, float) else f"{k}={v}" for k, v in res.items()))
            print(f"{'':25s}ambulance trips: {res['amb_trips']}")

    names = list(runs)
    agg = {n: {k: mean_std([r[k] for r in runs[n]]) for k, _, _ in METRICS} for n in names}

    lines = [f"# Fixed-time vs CivicSignal (adaptive)\n",
             f"Seeds: {', '.join(map(str, seeds))} · sim length {end} s · ambulances dispatched at "
             f"t={', '.join(map(str, AMB_TIMES if end >= AMB_TIMES[-1] + 300 else AMB_TIMES_QUICK))} s "
             f"(same times in both sims) · mean ± std over seeds, all seeds reported\n",
             "| Metric | " + " | ".join(names) + " | Adaptive vs fixed |",
             "|---|" + "---|" * len(names) + "---|"]
    for k, label, _ in METRICS:
        lines.append(f"| {label} | " + " | ".join(fmt(agg[n][k]) for n in names)
                     + f" | {pct(agg['fixed'][k][0], agg['adaptive'][k][0])} |")

    f, a = agg["fixed"], agg["adaptive"]
    d_delay = pct(f["delay_s"][0], a["delay_s"][0])
    d_co2 = pct(f["co2_kg"][0], a["co2_kg"][0])
    d_idle = pct(f["idle_co2_kg"][0], a["idle_co2_kg"][0])
    amb = (f"{a['amb_s'][0] - f['amb_s'][0]:+.0f} s" if f["amb_s"][0] is not None and a["amb_s"][0] is not None
           else "n/a")
    summary = f"**Adaptive vs fixed: {d_delay} delay, {d_co2} CO₂ ({d_idle} idling CO₂), ambulance {amb}**"
    lines += ["", summary, "", "Ambulance trips per dispatch (s):", ""]
    for i, seed in enumerate(seeds):
        for n in names:
            lines.append(f"- seed {seed} {n}: {', '.join(f'{x:.0f}' for x in runs[n][i]['amb_trips'])}")
    lines += ["", "## Per seed", "", "| Seed | Controller | " + " | ".join(l for _, l, _ in METRICS) + " |",
              "|---|---|" + "---|" * len(METRICS)]
    for i, seed in enumerate(seeds):
        for n in names:
            r = runs[n][i]
            lines.append(f"| {seed} | {n} | " + " | ".join("n/a" if r[k] is None else f"{r[k]:.1f}"
                                                          for k, _, _ in METRICS) + " |")
    (RESULTS / "compare.md").write_text("\n".join(lines) + "\n")

    with open(RESULTS / "compare.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["seed", "controller"] + [k for k, _, _ in METRICS])
        for i, seed in enumerate(seeds):
            for n in names:
                w.writerow([seed, n] + [runs[n][i][k] for k, _, _ in METRICS])

    print()
    print("\n".join(lines[2:3 + len(METRICS) + 1]))
    print()
    print(summary.replace("**", ""))
    print(f"\nwrote {RESULTS / 'compare.md'} and compare.csv")


if __name__ == "__main__":
    main()
