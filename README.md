# CivicSignal: adaptive traffic lights the city can steer

Hackachusetts 2026. A 3×3 downtown grid is simulated twice in [SUMO](https://eclipse.dev/sumo/) with identical
traffic. On the left, today's fixed-time signals. On the right, CivicSignal: a weighted max-pressure controller
(Varaiya 2013) that reads live queues at every intersection and picks the best green. City sliders choose what it
optimizes, and an ambulance button shows emergency preemption clearing a corridor.

## Results (3 seeds, 40 simulated minutes each, all seeds reported)

| | Fixed-time | CivicSignal | Change |
|---|---|---|---|
| Avg delay per vehicle | 35.9 ± 3.2 s | 13.7 ± 0.5 s | **−62%** |
| Idling CO₂ (wasted) | 152.7 ± 14.2 kg | 56.5 ± 2.1 kg | **−63%** |
| Total CO₂ | 634 ± 32 kg | 576 ± 8 kg | **−9%** |
| Ambulance trip (mean of 5 rush-hour dispatches) | 125.9 ± 12.4 s | 78.5 ± 1.8 s | **−47 s** |
| Stops per vehicle | 1.5 | 1.9 | +24% |
| Throughput / teleports | 2,744 / 0 | 2,748 / 0 | same |

Full table and per-seed numbers: [`results/compare.md`](results/compare.md). Reproduce with
`python compare.py --seeds 1 2 3` (about 1 minute).

Demand is asymmetric and time-varying: off-peak, then a 20-minute rush with the east-west axis at 3× the cross
streets, then off-peak again. Adaptive control gains most when demand is uneven. That's realistic, not rigged,
and the gap is smaller under uniform demand.

## Run it

Needs Python 3.10+ and macOS 15+ (or Linux/Windows) for the SUMO pip wheel.

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python server.py                      # → http://localhost:8000
```

The generated scenario is committed. To rebuild it: `python scenario/build.py`.
Tests: `python -m pytest -q tests` (no SUMO needed).

**Dashboard controls:** Space plays and pauses, A dispatches the ambulance. Presets set the sliders. Speed 1× = 10 sim
seconds per real second. Rush hour starts at 10:00 sim time, so run at 10× until about 9:00, then slow down.

## Demo backups (never skip these)

1. **Replay through the server:** <http://localhost:8000/?replay=/recordings/demo.jsonl&t=600>
   (`t` jumps to a sim second, `&autoplay` starts playing). The recording dispatches an ambulance at 15:50.
2. **No Python server at all:** from the repo root run `python3 -m http.server 8001`, then open
   <http://localhost:8001/web/?replay=/recordings/demo.jsonl&t=600>.
3. **Re-record** (deterministic, about 30 s): `python server.py --record recordings/demo.jsonl`.

Every live session is also recorded to `recordings/<timestamp>.jsonl` (gitignored).

## How it works

- `scenario/build.py`: `netgenerate` 3×3 grid, flows from fringe to fringe, a bus line, the ambulance route, and `web/net.json`.
- `core/sumo_runner.py`: one headless SUMO per side via TraCI subscriptions. Builds per-lane observations and the frame for the browser.
- `core/controller.py`: weighted max-pressure. Score of a green =
  `flow·(queue in − queue out) + climate·idling CO₂ + transit·5·buses + fairness·longest wait/30`.
  Min-green 8 s, max-green 60 s, 3 s yellow plus 1 s all-red on every change, hysteresis 2.
- **Emergency preemption:** each light sees the ambulance's distance to its stop line along the route
  (`getNextTLS`), so lights ahead clear their queues before it arrives (range 300 m). Yellow is never skipped.
- `server.py`: FastAPI on one port that serves `web/`, streams both sims over `/ws`, and records every frame.
- `web/`: plain HTML, CSS and JS with no build step. Chart.js is vendored so the demo works offline.

## Honest caveats

- Adaptive stops cars more often (+24%) but for much less time. Net time loss is −41%.
- Simulation, not field data: SUMO's HBEFA emission model, a synthetic grid, and synthetic demand.
- The baseline is SUMO's default fixed-time program (90 s cycle, even split): the common real-world setup, not an
  actuated controller.
