"""Headless comparison of signal strategies (spec 5.4, extended to every baseline and map).

    python compare.py --quick                          # Midtown, 1 seed, 900 s, for checkpoints
    python compare.py --scenario all --seeds 1 2 3     # the numbers for the slides (a few minutes)

Every strategy sees identical demand (same seed) and the same ambulance dispatches. Results go to
results/compare_<scenario>.md and .csv, with mean ± std over seeds and every seed reported.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
STRATEGIES = ["fixed", "actuated", "greenwave", "adaptive"]
LABELS = {"fixed": "Fixed-time", "actuated": "Actuated", "greenwave": "Green wave", "adaptive": "CivicSignal"}
AMB_TIMES = [700, 900, 1100, 1300, 1500]   # several rush-hour dispatches: one is a coin flip on fixed-time phase
AMB_TIMES_QUICK = [550, 700]
USD_PER_GAL, L_PER_GAL = 3.5, 3.785

METRICS = [  # key, label, lower is better
    ("delay_s", "Avg delay / vehicle (s)", True),
    ("time_loss_s", "Avg time loss / vehicle (s)", True),
    ("stops", "Stops / vehicle", True),
    ("throughput", "Trips completed", False),
    ("co2_kg", "Total CO₂ (kg)", True),
    ("idle_co2_kg", "Idling CO₂ (kg)", True),
    ("fuel_usd", "Fuel burned ($)", True),
    ("nox_g", "NOx (g)", True),
    ("pm_g", "Particulates (g)", True),
    ("bus_s", "Bus trip (s)", True),
    ("amb_s", "Ambulance trip, mean of dispatches (s)", True),
    ("teleports", "Teleports (gridlock)", True),
]


def run_one(job: tuple[str, str, int, int]) -> dict:
    scenario, strategy, seed, end = job
    from core.controller import BALANCED, WeightedMaxPressure
    from core.sumo_runner import PROGRAMS, SumoRunner
    from core.types import Weights

    cfg = json.loads((ROOT / "scenario" / scenario / "meta.json").read_text())["cfg"]
    trip = RESULTS / f"tripinfo_{scenario}_{strategy}_s{seed}.xml"
    ctrl = WeightedMaxPressure(Weights(**BALANCED)) if strategy == "adaptive" else None
    t0 = time.time()
    r = SumoRunner(f"{scenario}_{strategy}_{seed}", str(ROOT / cfg), seed, ctrl, tripinfo=str(trip),
                   program=PROGRAMS.get(strategy, "0"))
    amb_times = AMB_TIMES if end >= AMB_TIMES[-1] + 300 else AMB_TIMES_QUICK
    m = {}
    while r.t < end:
        if r.t in amb_times:
            r.spawn_ambulance()
        m = r.step()["m"]
    amb, bus = list(r.amb_trips), list(r.bus_trips)
    r.close()

    trips = [t for t in ET.parse(trip).getroot().iter("tripinfo") if not t.get("id").startswith("amb")]
    n = max(1, len(trips))
    co2_mg = sum(float(t.find("emissions").get("CO2_abs")) for t in trips if t.find("emissions") is not None)
    trip.unlink()
    return {
        "scenario": scenario, "strategy": strategy, "seed": seed, "secs": round(time.time() - t0, 1),
        "delay_s": sum(float(t.get("waitingTime")) for t in trips) / n,
        "time_loss_s": sum(float(t.get("timeLoss")) for t in trips) / n,
        "stops": sum(float(t.get("waitingCount")) for t in trips) / n,
        "throughput": m["arrived"],
        "co2_kg": co2_mg / 1e6,
        "idle_co2_kg": m["idle_co2_kg"],
        "fuel_usd": m["fuel_l"] / L_PER_GAL * USD_PER_GAL,
        "nox_g": m["nox_g"],
        "pm_g": m["pm_g"],
        "bus_s": statistics.mean(bus) if bus else None,
        "amb_s": statistics.mean(amb) if amb else None,
        "amb_trips": amb,
        "teleports": m["teleports"],
    }


def mean_std(xs: list) -> tuple[float | None, float]:
    xs = [x for x in xs if x is not None]
    if not xs:
        return None, 0.0
    return statistics.mean(xs), statistics.stdev(xs) if len(xs) > 1 else 0.0


def fmt(ms: tuple[float | None, float], dec: int = 1) -> str:
    m, s = ms
    if m is None:
        return "n/a"
    return f"{m:,.{dec}f} ± {s:,.{dec}f}" if s else f"{m:,.{dec}f}"


def pct(base: float | None, new: float | None) -> str:
    if base is None or new is None or base == 0:
        return "n/a"
    return f"{(new - base) / base * 100:+.1f}%"


def report(scenario: str, rows: list[dict], seeds: list[int], end: int) -> str:
    strategies = [s for s in STRATEGIES if any(r["strategy"] == s for r in rows)]
    by = {s: [r for r in rows if r["strategy"] == s] for s in strategies}
    agg = {s: {k: mean_std([r[k] for r in by[s]]) for k, _, _ in METRICS} for s in strategies}
    title = json.loads((ROOT / "scenario" / scenario / "meta.json").read_text())["title"]
    amb_times = AMB_TIMES if end >= AMB_TIMES[-1] + 300 else AMB_TIMES_QUICK
    lines = [f"# {title}: signal strategies compared\n",
             f"Seeds {', '.join(map(str, seeds))} · {end} s simulated · ambulances dispatched at "
             f"t = {', '.join(map(str, amb_times))} s in every run · CivicSignal runs the Balanced policy "
             f"(flow 1, climate 1, transit 0.5) · mean ± std over seeds, every seed reported below\n",
             "| Metric | " + " | ".join(LABELS[s] for s in strategies) + " | CivicSignal vs best baseline |",
             "|---|" + "---|" * len(strategies) + "---|"]
    wins = 0
    for k, label, lower in METRICS:
        dec = 2 if k == "stops" else 0 if k in ("throughput", "teleports", "nox_g", "co2_kg") else 1
        cells = []
        means = {s: agg[s][k][0] for s in strategies}
        valid = {s: v for s, v in means.items() if v is not None}
        best = (min if lower else max)(valid.values()) if valid else None
        for s in strategies:
            c = fmt(agg[s][k], dec)
            cells.append(f"**{c}**" if best is not None and means[s] == best and k != "teleports" else c)
        others = {s: v for s, v in valid.items() if s != "adaptive"}
        if "adaptive" in valid and others:
            base_s = (min if lower else max)(others, key=others.get)
            cmp = f"{pct(others[base_s], valid['adaptive'])} vs {LABELS[base_s]}"
            better = valid["adaptive"] < others[base_s] if lower else valid["adaptive"] > others[base_s]
            wins += better and k != "teleports"
        else:
            cmp = "n/a"
        lines.append(f"| {label} | " + " | ".join(cells) + f" | {cmp} |")
    lines.append(f"\nCivicSignal beats the best baseline on **{wins} of {len(METRICS) - 1}** metrics (bold = best).\n")
    if "fixed" in agg and "adaptive" in agg:
        f, a = agg["fixed"], agg["adaptive"]
        amb = (f"{a['amb_s'][0] - f['amb_s'][0]:+.0f} s" if f["amb_s"][0] is not None and a["amb_s"][0] is not None else "n/a")
        lines.append(f"**vs Fixed-time: {pct(f['delay_s'][0], a['delay_s'][0])} delay, {pct(f['co2_kg'][0], a['co2_kg'][0])} CO₂, "
                     f"{pct(f['stops'][0], a['stops'][0])} stops, ambulance {amb}**\n")
    lines += ["## Every run", "", "| Seed | Strategy | " + " | ".join(l for _, l, _ in METRICS) + " | Ambulance trips (s) |",
              "|---|---|" + "---|" * (len(METRICS) + 1)]
    for r in sorted(rows, key=lambda r: (r["seed"], STRATEGIES.index(r["strategy"]))):
        lines.append(f"| {r['seed']} | {LABELS[r['strategy']]} | "
                     + " | ".join("n/a" if r[k] is None else f"{r[k]:,.1f}" for k, _, _ in METRICS)
                     + f" | {', '.join(f'{x:.0f}' for x in r['amb_trips'])} |")
    text = "\n".join(lines) + "\n"
    (RESULTS / f"compare_{scenario}.md").write_text(text)
    with open(RESULTS / f"compare_{scenario}.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["seed", "strategy"] + [k for k, _, _ in METRICS])
        for r in rows:
            w.writerow([r["seed"], r["strategy"]] + [r[k] for k, _, _ in METRICS])
    return text


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="midtown", help="grid, midtown, or all")
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3])
    ap.add_argument("--strategies", nargs="+", default=STRATEGIES)
    ap.add_argument("--quick", action="store_true", help="1 seed, 900 s")
    ap.add_argument("--end", type=int, default=2400)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    scenarios = ["grid", "midtown"] if args.scenario == "all" else [args.scenario]
    seeds, end = ([args.seeds[0]], 900) if args.quick else (args.seeds, args.end)
    RESULTS.mkdir(exist_ok=True)

    jobs = [(sc, st, seed, end) for sc in scenarios for seed in seeds for st in args.strategies]
    rows = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for r in pool.map(run_one, jobs):
            rows.append(r)
            print(f"{r['scenario']:8s} seed {r['seed']} {LABELS[r['strategy']]:11s} {r['secs']:5.1f}s  delay={r['delay_s']:.1f} "
                  f"stops={r['stops']:.2f} co2={r['co2_kg']:.0f} amb={r['amb_s'] and round(r['amb_s'])} bus={r['bus_s'] and round(r['bus_s'])}", flush=True)
    for sc in scenarios:
        print("\n" + report(sc, [r for r in rows if r["scenario"] == sc], seeds, end).split("## Every run")[0])


if __name__ == "__main__":
    main()
