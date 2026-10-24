# CivicSignal: traffic lights the city can steer

Hackachusetts 2026. CivicSignal is an adaptive traffic-signal controller for **54 real intersections in Midtown
Manhattan** (6th to 3rd Ave, 47th to 55th St, imported from OpenStreetMap). We race it against the three ways cities
time lights today: fixed timers, detector-actuated lights, and a coordinated green wave. Every strategy gets the
same cars, the same seed, and the same emergencies, side by side.

The city sets the priorities on four dials: **Flow, Climate, Transit and Fairness**. A plain-English policy
copilot (Gemini) can set them too. Every decision stays a formula you can click on and audit.

## Results: Midtown Manhattan (3 seeds, 40-minute rush hour, all seeds reported)

| | Fixed-time | Actuated | Green wave | **CivicSignal** |
|---|---|---|---|---|
| Avg delay / vehicle | 143.1 s | 25.1 s | 51.0 s | **24.1 s** |
| Time loss / vehicle | 184.8 s | 55.7 s | 74.2 s | **48.8 s** |
| Total CO₂ | 1,871 kg | 1,135 kg | 1,141 kg | **1,041 kg** |
| Fuel burned | $755 | $459 | $461 | **$420** |
| NOx (smog, asthma) | 705 g | 391 g | 409 g | **360 g** |
| Ambulance trip (15 dispatches) | 546 s | 255 s | 274 s | **158 s** |
| Stops / vehicle | 5.86 | 3.68 | **2.16** | 2.68 |
| Bus trip (5th & Madison) | 292 s | 122 s | **84 s** | 101 s |
| Gridlock teleports | 7 | 0 | 0 | 0 |

**CivicSignal beats the best baseline on 8 of 11 metrics.** Against today's fixed timers it cuts delay by 83%,
CO₂ by 44% and stops by 54%, and gets the ambulance there **6.5 minutes sooner**. The green wave still wins on stops,
buses and particulates, because Manhattan's avenues and bus routes are what it was designed for. We report that.
Full tables with ± std and every run: [`results/compare_midtown.md`](results/compare_midtown.md).

On the 3×3 **demo grid** ([`results/compare_grid.md`](results/compare_grid.md)), actuated control wins on delay
(7.2 s vs 11.7 s), and CivicSignal wins the ambulance (−33%) and buses (−8%). With the Climate dial at 3,
CivicSignal also beats actuated on stops and CO₂. That's the trade-off the city gets to choose.

Reproduce everything with `python compare.py --scenario all --seeds 1 2 3` (about 6 minutes on a laptop).

## What you can do in the dashboard

- **Compare** CivicSignal against any baseline, or watch all four strategies at once ("four cities, same traffic").
- **Stress-test:** 🚑 dispatch an ambulance to Mount Sinai West, 🎭 let out a Radio City show (160 cars), or 💥 crash
  two lanes of 5th Ave at St. Patrick's. Every event hits every city at the same second.
- **Steer:** presets (Balanced, Commute, Climate, Transit, Fairness), four sliders, emergency preemption, or type a
  policy for the ✨ copilot.
- **Audit:** click any intersection to see what each strategy is doing there, and CivicSignal's full score: why this
  light is green, term by term.
- **Follow a driver:** click any car to follow the same driver in every city, with a trip timer.
- **Impact:** live scoreboard (since start, or the last 2 minutes), money and health (fuel $, NOx, particulates),
  and a back-of-envelope yearly estimate.
- **🔥 Heat:** an emissions heatmap of where the CO₂ piles up.
- **Pop-out windows (⧉):** any panel opens in its own window, and all windows stay in sync.

Keys: Space play/pause · A ambulance · S surge · C crash · H heatmap · Esc stop following.

## Run it

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python server.py                     # → http://localhost:8000
```

The policy copilot needs a Gemini key in a `.env` file at the repo root (gitignored):
`GEMINI_API_KEY=...`. Everything else works without it.

Useful URLs for recording: `?tab=inspect` opens a tab, `?heat` turns the heatmap on, `?view=impact` shows only a
panel. Rebuild the maps with `python scenario/build.py`. Run the tests with `python -m pytest -q tests`.

**Replays:** `python server.py --record recordings/x.jsonl --scenario midtown --events 950:ambulance,1000:surge`
writes a deterministic run, and `http://localhost:8000/?replay=/recordings/x.jsonl&t=600` plays it back
(`&autoplay` starts it). `recordings/demo.jsonl` is a committed grid backup.

## How it works

- **Controller** (`core/controller.py`): weighted max-pressure (Varaiya 2013). Each light scores every green it could show:
  `flow·(queue in − queue out) + climate·(moving cars a red would stop) + transit·5·(buses) + fairness·(longest wait)/30`.
  It switches when another green beats the current one by 2, with 8 s minimum green, 60 s maximum, and a 3 s yellow
  plus 1 s all-red on every change. Emergency vehicles get a green corridor: every light on the ambulance's route
  clears its queue before it arrives, and never skips a yellow.
- **Advance detection:** OpenStreetMap splits some approaches into 12–65 m segments. Counting only the last segment
  made one light on Madison Ave starve the avenue. Now each light sees its whole approach back to the previous signal,
  like real advance loop detectors.
- **Baselines** (`scenario/build.py`): fixed-time is SUMO's default 90 s program. Actuated runs the same phases with
  gap-out on detectors (6–55 s greens). The green wave favours the avenues 52/32 and offsets each light by travel time.
- **Simulation:** SUMO 1.28 via TraCI, one headless process per strategy, stepped in lockstep by a FastAPI server that
  broadcasts every frame over a websocket. The frontend is plain HTML, JS and canvas, with no build step.

## Honest caveats

- Simulation, not field data: SUMO's HBEFA emission model, with synthetic demand on real Manhattan geometry.
  Signal timings in the baselines are reasonable defaults, not NYC DOT's actual plans.
- The ambulance is a regular car that obeys signals. Without preemption it would sit in traffic in every city.
- The yearly estimate scales this run's savings to 2 rush hours × 250 weekdays. It's a back-of-envelope figure,
  not a forecast.

Map data © OpenStreetMap contributors (ODbL).
