# CivicSignal — adaptive traffic lights the city can steer

> Hackachusetts 2026 · solo build (team of 3 registered) · ~6 hours · themes: traffic flow + climate + civics
> Working name; rename freely. This file is the spec for Claude Code sessions on this repo.
> **Contracts (section 4) are frozen: change them only additively, and log changes in section 6.**

---

## 1. The idea in one paragraph

A 3×3 downtown grid is simulated twice, side by side, with identical traffic: on the left, today's
**fixed-time** signals; on the right, **CivicSignal**, a weighted max-pressure controller that reads
live queues and picks the best green at every intersection. A dashboard shows the gap growing in real
time: average delay, CO₂ (total and *wasted idling*), throughput, and how long the worst-off driver
has waited. Then come the two demo moments. First, an **ambulance button**: on the left it sits in
traffic, on the right the signals clear a corridor. Second, **policy sliders** (Flow / Climate /
Transit / Fairness): the city chooses what to optimize, and the lights adapt. The pitch is that
*a black box shouldn't decide this; the city should.*

**Theme fit**
- Traffic: max-pressure control, a well-studied adaptive algorithm (Varaiya 2013), vs a fixed-time baseline
- Climate: SUMO's built-in emission model gives CO₂ per vehicle. Idling CO₂ is the headline number
- Civics: emergency preemption, transit priority, a fairness cap, and a transparent "city report card"

---

## 2. Hard constraints (8 GB M3 MacBook, 6 hours)

The whole stack needs well under 1.5 GB of RAM. The real risk is everything else running on the laptop.

**Do**
- Run SUMO **headless** (`sumo`, never `sumo-gui`), so no XQuartz is needed
- Use a plain HTML/JS frontend with Chart.js from cdnjs. **No npm, no build step**
- Use one Python process (FastAPI) that serves the web page and the websocket on `localhost:8000`
- Close Docker Desktop, extra Chrome tabs, and Slack desktop. Watch Activity Monitor → Memory Pressure (red = close things)

**Don't (cut list, final)**
- No RL training, YOLO/PyTorch/camera input, or local LLMs
- No pedestrians in SUMO, no sumo-gui, no Docker, no deployment, no database, no auth
- No React, Next.js, or Vite (dev servers eat RAM and setup time)

**Python 3.10+.** macOS's built-in `python3` may be 3.9. Check with `python3 --version`.
If it's older, run `brew install python@3.12` (or use `uv venv --python 3.12`).
Every module starts with `from __future__ import annotations` anyway.

---

## 3. Setup and the 25-minute install timebox

```bash
sw_vers -productVersion          # pip SUMO wheel for Apple Silicon needs macOS 15+
python3 -m venv .venv && source .venv/bin/activate
pip install eclipse-sumo traci sumolib fastapi "uvicorn[standard]"
sumo --version && netgenerate --version
python -c "import sumo; print(sumo.SUMO_HOME)"
```

**If something fails, work down this list. Stop at T+0:25 no matter what.**
1. `Library not loaded: ...xerces/proj/gdal...` → `brew install xerces-c fox proj gdal gl2ps`, then retry
2. macOS < 15, or the wheel won't install → install the official `sumo-1.28.0.pkg` from sumo.dlr.de/docs/Downloads.php
   (the docs say it wants XQuartz installed too), set `export SUMO_HOME=...`, then `pip install traci==1.28.0 sumolib==1.28.0`
3. SUMO works on **any one** teammate laptop (Windows/Linux wheels are self-contained) → that laptop
   runs the server and the demo. Everyone else develops against fake data and mock frames (see section 4)
4. Nothing works by T+0:25 → **Plan B** (section 9): a pure-Python queue sim behind the same interfaces. The controller and frontend work is unaffected.

`traci` and `sumolib` versions must match the SUMO version.

---

## 4. Contracts (frozen)

### 4.1 Repo layout and ownership

```
civicsignal/
  CLAUDE.md                  # this file (everyone)
  requirements.txt           # B
  core/
    types.py                 # A: copy verbatim from 4.2 at T+0
    controller.py            # A: WeightedMaxPressure + PhaseManager
    sumo_runner.py           # B: SumoRunner (sim + observations + frames)
  scenario/
    build.py                 # B: netgenerate + routes + sumocfg
    grid.net.xml, routes.rou.xml, sim.sumocfg   (generated)
  compare.py                 # A: headless batch comparison → results/
  server.py                  # B: FastAPI, static web/, /ws websocket
  tests/                     # A
  web/                       # C: index.html, app.js, style.css
    net.json, mock_frames.json   # B produces, C consumes
  recordings/                # B: *.jsonl replays (demo backup)
  pitch/                     # C: slides, script, screen recording
  results/                   # A: compare.md, compare.csv
```

Own your files. Don't edit someone else's file without telling them. Pull before integrating.

### 4.2 `core/types.py` (paste verbatim)

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Protocol

@dataclass
class Weights:
    flow: float = 1.0       # queue pressure (max-pressure)
    climate: float = 0.0    # CO2 rate of idling vehicles on the approach
    transit: float = 0.0    # halted buses on the approach
    fairness: float = 0.0   # longest wait on the approach
    preempt: bool = True    # emergency-vehicle preemption

@dataclass
class TLSInfo:                       # static, built once per traffic light
    tls_id: str
    links: list[tuple[str, str]]     # signal index -> (in_lane, out_lane)
    green_states: list[str]          # candidate green RYG strings (from default program)
    initial_state: str

@dataclass
class LaneObs:                       # dynamic, built every step for each lane touching a TLS
    halting: int = 0                 # vehicles with speed < 0.1 m/s
    co2_mg_s: float = 0.0            # summed CO2 rate (mg/s) of halted vehicles
    buses: int = 0                   # halted buses
    max_wait_s: float = 0.0          # longest consecutive wait of any vehicle on lane
    emergency_dist_m: Optional[float] = None   # nearest emergency vehicle's distance to stop line

class Controller(Protocol):
    weights: Weights
    def register(self, info: TLSInfo) -> None: ...
    def step(self, tls_id: str, t: float, lanes: dict[str, LaneObs]) -> str: ...
        # returns the full RYG state string to display NOW (handles yellow internally)
```

The fixed-time baseline is **no controller**. SUMO runs its default static program, and the runner never calls `setRedYellowGreenState`.

### 4.3 `SumoRunner` (B implements, A and server use)

```python
class SumoRunner:
    def __init__(self, label: str, cfg: str, seed: int,
                 controller: Controller | None,      # None => fixed-time baseline
                 tripinfo: str | None = None): ...   # path => write tripinfo with emissions
    def step(self) -> dict: ...          # advance 1 s, apply controller, return {"veh","sig","m"} (4.4)
    def spawn_ambulance(self) -> None: ...
    def close(self) -> None: ...
```

### 4.4 Websocket frame: server → browser (one per sim step)

```json
{
  "type": "frame",
  "t": 412,
  "sims": {
    "fixed":    { "veh": [["v12", 123.4, 56.7, 90.0, "c", 1]],
                  "sig": { "B0A0_0": "G", "A1A0_0": "r" },
                  "m":   { "...metrics, see below..." : 0 } },
    "adaptive": { "veh": [], "sig": {}, "m": {} }
  },
  "events": ["ambulance_spawned"]
}
```
- `veh` item: `[id, x, y, angle_deg, kind, halted]`. Kind is `"c"` car, `"b"` bus, or `"e"` emergency. Halted is 0/1.
  SUMO coordinates are in meters with **y pointing up** (flip for canvas). Angle is degrees **clockwise from north**.
- `sig`: incoming lane id → `"G"|"y"|"r"`. A lane is `G` if any of its links is G/g. Draw a dot at the lane's last shape point.
- `m` (metrics, cumulative since t=0 unless noted):

| key | meaning |
|---|---|
| `t` | sim seconds |
| `running`, `arrived` | vehicles in network now / finished so far |
| `avg_delay_s` | total halted vehicle-seconds ÷ (arrived + running) |
| `queue` | halted vehicles now |
| `co2_kg` | Σ CO₂ rate × dt over all vehicles |
| `idle_co2_kg` | same, halted vehicles only (the "wasted" CO₂, the headline climate number) |
| `max_wait_s` | longest current consecutive wait of any vehicle (fairness) |
| `teleports` | SUMO teleports (gridlock indicator; report it, don't hide it) |
| `amb_active`, `amb_elapsed_s`, `amb_last_trip_s` | ambulance status |
| `tls_wait` | optional: `{tls_id: avg halted per approach}` for the report card |

### 4.5 Browser → server messages

```json
{"type":"weights","flow":1.0,"climate":0.5,"transit":0.0,"fairness":0.0,"preempt":true}
{"type":"ambulance"}
{"type":"control","action":"play"}      // "play" | "pause" | "reset"
{"type":"speed","sps":10}               // sim steps per second
```
Weights apply to the adaptive sim only. The ambulance spawns in **both** sims at the same step.

### 4.6 `web/net.json` (static, exported once by B via sumolib)

```json
{"bounds":[xmin,ymin,xmax,ymax],
 "lanes":[{"id":"A0B0_0","shape":[[x,y],[x,y]],"w":3.2}],
 "tls":[{"id":"A0","x":0.0,"y":0.0}]}
```
Exclude internal lanes (ids starting with `:`).

---

## 5. Technical spec per component

### 5.1 Scenario (B): `scenario/build.py`

```bash
netgenerate --grid --grid.number=3 --grid.length=200 --grid.attach-length=200 \
  --default.lanenumber=2 -j traffic_light -o scenario/grid.net.xml
```
(If an option name errors, check `netgenerate --help`. Spend no more than 5 minutes on it.)
- Find fringe edges with `sumolib.net.readNet(...)`. Don't hard-code edge ids; inspect the generated net.
- `routes.rou.xml`:
  - vTypes: `car` (default), `bus` (vClass="bus", length 12), `ambulance` (vClass="emergency", speedFactor 1.3)
  - Flows use `from`/`to` (SUMO routes them itself), fringe→opposite fringe plus some turns.
    **Asymmetric, time-varying demand**: 0–600 s low; 600–1800 s rush (main axis ~3× the cross street); 1800–2400 s low.
    Adaptive control shines when demand is uneven. That's realistic, not rigged. Say so in the pitch.
  - Bus flow on one corridor, period ~120 s.
  - `<route id="amb_route" edges="..."/>` diagonal-ish across the grid, computed with `net.getShortestPath(a, b)`.
- `sim.sumocfg`: end 2400, step-length 1, `time-to-teleport` 300, `no-step-log` true.
- Same `--seed` for both sims, so the demand is identical.
- Could (only after T+3:15): an actuated-baseline net (`--tls.default-type actuated`) for compare.py.

### 5.2 SumoRunner (B): `core/sumo_runner.py`

```python
traci.start(["sumo", "-c", cfg, "--seed", str(seed)] + extra, label=label)
conn = traci.getConnection(label)        # use conn.* everywhere; two sims coexist
```
- **Use subscriptions from the start**, because per-vehicle getters are too slow for two sims at 10 steps/s:
  ```python
  import traci.constants as tc
  VARS = [tc.VAR_POSITION, tc.VAR_ANGLE, tc.VAR_TYPE, tc.VAR_SPEED, tc.VAR_CO2EMISSION,
          tc.VAR_WAITING_TIME, tc.VAR_LANE_ID, tc.VAR_LANEPOSITION]
  for vid in conn.simulation.getDepartedIDList(): conn.vehicle.subscribe(vid, VARS)
  res = conn.vehicle.getAllSubscriptionResults()   # {vid: {var: value}}
  ```
- Build `LaneObs` per lane by grouping `res` by lane id (skip lanes starting with `:`). Halted means speed < 0.1.
  `emergency_dist_m` = lane length − lane position for type `ambulance`. Cache lane lengths from sumolib.
- `TLSInfo` per light: `links[i] = conn.trafficlight.getControlledLinks(tls)[i][0][:2]` (in, out).
  `green_states` = phases of `getCompleteRedYellowGreenDefinition(tls)[0]` that contain G/g and no `y`.
  **Only control lights with ≥ 2 distinct green states.** This filters out fringe dead-ends. Expect 9 for a 3×3 grid; assert it.
- Applying control: call `conn.trafficlight.setRedYellowGreenState(tls, s)` **only when `s` changed**.
  After the first call SUMO switches the light to program "online" and holds that state until the next call.
  State string length must equal `len(links)`.
- Metrics as in 4.4. CO₂ comes from `VAR_CO2EMISSION` (mg/s). Arrivals come from `conn.simulation.getArrivedNumber()`.
- `spawn_ambulance`: `conn.vehicle.add(f"amb{n}", "amb_route", typeID="ambulance")`, then track its depart and arrive steps.
- If `tripinfo` is set, add `--tripinfo-output <path> --device.emissions.probability 1`. That gives per-vehicle
  `waitingTime`, `timeLoss`, `waitingCount` (stops), plus `<emissions CO2_abs=... (mg)>`.

### 5.3 Controller (A): `core/controller.py`

`WeightedMaxPressure(weights)` keeps per-light state: current green, phase timer, and mode (green/yellow/allred).

Score of a candidate green state `g` (sum over link indices i where `g[i]` is G or g):
```
pressure term (per unique (in,out) pair):  w.flow     * (halting[in] - halting[out])
lane terms    (per unique in-lane):         w.climate  * co2_mg_s[in] / 1000
                                           + w.transit  * 5 * buses[in]
                                           + w.fairness * max_wait_s[in] / 30
```
Switching rules (constants at top of file):
- `MIN_GREEN=8`, `MAX_GREEN=60`, `YELLOW=3`, `ALL_RED=1`, `HYST=2.0`
- Keep the current green if `t_in_green < MIN_GREEN`.
- Switch to the best state if `score(best) > score(cur) + HYST`, or if `t_in_green >= MAX_GREEN`.
  At max green with best == cur, take the second best (prevents starvation).
- **Preemption** (if `w.preempt`): an emergency vehicle within 150 m on in-lane L → target = the green state serving L.
  This ignores MIN_GREEN but **never skips yellow**.
- Transition: yellow string = for each i, `'y'` if `cur[i]` is G/g and `target[i]` is not, else `cur[i]`.
  Then ALL_RED (every G/g/y → `r`), then target.
- `weights` is a public attribute. The server mutates it live.

Tests (`tests/test_controller.py`, no SUMO needed): fake 4-link `TLSInfo` with 2 green states.
Check that a heavy queue wins, min-green is respected, yellow always precedes a change, preemption works, and max-green rotates.

### 5.4 compare.py (A): the numbers for the slide

```
python compare.py --seeds 1 2 3            # fixed vs adaptive (vs actuated if built), full 2400 s
python compare.py --quick                  # 1 seed, 900 s, for checkpoints
```
- Run each controller headless with `tripinfo`. The ambulance auto-spawns at t=900 (mid-rush).
- Parse tripinfo XML and write `results/compare.md` and `results/compare.csv` with mean ± std over seeds:
  avg delay (waitingTime), avg time loss, stops/vehicle (waitingCount), total CO₂ kg, throughput, teleports,
  ambulance trip time. Add a summary line: `Adaptive vs fixed: −X% delay, −Y% CO₂, ambulance −Z s`.
- Report all seeds. No cherry-picking; judges ask.

### 5.5 Server (B): `server.py`

- FastAPI. `StaticFiles` serves `web/` at `/` and `recordings/` at `/recordings`. The websocket is at `/ws`.
- One asyncio task loop: step both runners (fast, synchronous), `await ws.send_json(frame)`, then `await asyncio.sleep(1/sps)`.
  A second task reads client messages (4.5) and applies them.
- Every frame is also appended to `recordings/<timestamp>.jsonl`.
- Reset = close both runners and start fresh ones (same seed).
- If stepping is slow, send every 2nd frame. Don't block on the browser.

### 5.6 Frontend (C): `web/`

Layout (one screen, 1440×900 projector-friendly):
- **Top:** two canvases side by side, "Fixed-time (today)" and "CivicSignal (adaptive)", with identical scale.
  Draw lanes once to an offscreen canvas. Vehicles are small rotated rects (car grey, bus blue, ambulance red with a flashing outline).
  Halted vehicles get a subtle red tint. Signal dots go at lane ends.
- **Middle:** delta cards with big numbers: avg delay, idle CO₂, total CO₂, throughput, max wait, ambulance time.
  Each card shows fixed vs adaptive and the % difference (green when adaptive is better).
- **Bottom left:** a Chart.js line chart of cumulative idle CO₂ and queue length over time for both sims.
- **Bottom right:** control panel with four sliders (Flow, Climate, Transit, Fairness, each 0–3), a preempt toggle,
  a big 🚑 **Dispatch ambulance** button, play/pause/reset, and a speed control.
- **Could:** a "City report card" grid of the 9 intersections colored by `tls_wait`.
- **Replay mode:** `index.html?replay=/recordings/demo.jsonl` plays a recording with no server sim (the demo backup).
- Until B delivers `net.json` and `mock_frames.json`, use a hand-made 1-intersection mock with the same schema.

---

## 6. Working mode (solo) and changes since the freeze

One person (`serial-optimizer`) builds everything. Teammates use Kiro and are optional helpers (Devpost write-up,
slides, presenting while the builder drives the demo). Nothing on the build path depends on them.

- The A/B/C ownership in 4.1 is historical: any file may be edited.
- Teammates may still push to the shared repo. Pull and look before writing, don't overwrite or delete their files
  without asking the user, and pull before every push.
- After any controller or scenario change: rerun `python -m pytest -q tests`, `python compare.py --seeds 1 2 3`,
  and `python server.py --record recordings/demo.jsonl`, then commit the refreshed `results/` and recording.

**Contract changes since the freeze.** These are additive only, so old callers still work. Keep it that way.
- `LaneObs.approaching` (moving vehicles on the lane) and `LaneObs.buses_moving` (moving buses), both defaulted.
- `SumoRunner(..., program="0")`: the SUMO program for controller-less runs (`"0"` fixed, `"actuated"`, `"greenwave"`).
  New methods: `surge()`, `crash()`, `inspect(tls_id)`.
- Frame `m` gains cumulative `halt_vs, veh_s, stops, fuel_l, nox_g, pm_g, bus_trips, bus_avg_trip_s`. A frame may carry
  `heat` ({edge: CO₂ g/s per 100 m}). `sims` is keyed by strategy (`fixed|actuated|greenwave|adaptive`), with 2 or 4 panes.
- Server → browser: `state` (weights, panes, scenarios, copilot availability, inspected light), `history` (chart
  backfill), and `frame.inspect`. Browser → server: `event` {ambulance|surge|crash}, `inspect` {tls}, and `config`
  {scenario, panes}, `follow` {vid}. `POST /api/copilot` turns plain English into weights via Gemini (key read from
  `.env`, spaces allowed). Models are tried in order (`MODELS` in server.py, gemini-2.5-flash first: about 4 s);
  400/404/429/5xx fall through to the next, because free-tier keys have zero quota on some models.
- One sim loop broadcasts to every connected window. Windows share the sim, so a test driver must use its own
  port (`python server.py --port 8010`).

**Deliberate deviations from section 5. Don't "fix" these back.**
- Maps live in `scenario/<id>/` with `meta.json`, built by `python scenario/build.py`. Midtown is the 54-signal OSM
  import (6th–3rd Ave, 47th–55th St). The grid is kept as the demo city.
- 5.2: use `trafficlight.getAllProgramLogics`. In traci 1.28 `getCompleteRedYellowGreenDefinition` is the deprecated
  alias. Teleporting vehicles report sentinel emissions of about −1e9 and are skipped.
- 5.2 advance detection: segments chained to a signal's approach (through non-signal nodes, up to 250 m) report into
  that approach's `LaneObs`. Without it, Midtown seed 2 delay was 38 s instead of 25 s (OSM splits Madison Ave).
- 5.3 preemption: the range is 300 m, and every light on the ambulance's route gets its distance (`getNextTLS`).
- 5.3 climate term: `climate · (moving vehicles on the approach)` instead of idle CO₂. The spec's version measured
  +3% CO₂. Transit counts approaching buses too (transit signal priority).
- CivicSignal's default policy is `BALANCED` in `core/controller.py` (flow 1, climate 1, transit 0.5). The `Weights`
  dataclass defaults are unchanged.
- 5.4: `compare.py` runs every strategy on every map (`--scenario all`), with the ambulance metric averaged over
  5 dispatches. Results are in `results/compare_<map>.md`.
- 5.6: the frontend is a multi-view dashboard (Impact, Policy, Events and Inspect tabs, pop-outs via `?view=`).
  Chart.js is vendored.
- Hosting (despite "no deployment" in section 2): `deploy/streamlit_app.py` puts a replay-only copy on Streamlit
  Community Cloud. It inlines `web/` and the gzipped `recordings/demo.jsonl` into one `st.iframe`, and `app.js` reads
  `window.CIVIC_PARAMS` before `location.search`. The live sim still needs `server.py` (Streamlit can't host the websocket).
- Cut: `web/mock_frames.json`, the report card, OSM Amherst, and Plan B.

## 7. Status

- Done: Midtown and grid maps; four strategies; events; inspector; follow-a-driver; heatmap; copilot (needs a key
  in `.env`); replays; 3-seed benchmark (Midtown: CivicSignal best on 8 of 11 metrics); README; `pitch/script.md`
  (video shot list).
- Large Midtown recordings (about 45 KB per frame) are gitignored. The committed `recordings/demo.jsonl` is the grid.
- Keep a feature freeze 1 hour before submission. Re-run `compare.py` after any controller or scenario change.

## 8. Pitch (2 minutes) and judge Q&A

1. **Hook (15 s):** Every red light over an empty intersection costs time and burns fuel idling.
2. **Side by side (30 s):** Rush hour hits. The fixed-time queues grow while the adaptive side drains. Point at the delay and idle-CO₂ cards.
3. **Ambulance (25 s):** Dispatch. Left: stuck. Right: a green corridor. Show both trip times.
4. **Civics (30 s):** "Cities shouldn't get a black box." Move Climate up, and stops and total CO₂ drop. Move Fairness up, and max wait drops (numbers: `pitch/script.md`).
   "The city chooses its values; the lights carry them out."
5. **Results (20 s):** the compare.py table (3 seeds, mean ± std), plus a line on how it would deploy.

**Likely questions**
- *Is the baseline a strawman?* It's SUMO's default fixed-time program, the most common real-world setup.
  If built, also show the actuated baseline.
- *Why max-pressure, not RL?* It needs no training data, it's explainable, it has throughput-optimality results in the literature,
  and every decision can be audited. That's the civics point.
- *Deployment?* Queue counts come from existing loop detectors or cameras. The controller runs on a cabinet edge box.
  Min-green, yellow, all-red, and max-green bounds keep it safe.
- *Does it only work on your demand?* Show uniform vs rush demand honestly. Gains are biggest under uneven demand.

---

## 9. Plan B: pure-Python sim (only if SUMO is dead at T+0:25)

B writes `core/pysim.py` exposing the **same** `SumoRunner` interface (4.3) and frame schema (4.4):
- 3×3 grid; each approach is a FIFO queue. Poisson arrivals use the same demand profile as 5.1.
- Discharge rate is 0.5 veh/s per lane while green. Travel between intersections is fixed at ~15 s (interpolate positions for drawing).
- CO₂ is **estimated** with constant idle vs moving rates. Label it "estimated" in the UI and slides.
- `TLSInfo` has 2 green states per light (NS, EW) with 4 links each.

The controller (A) and frontend (C) need **zero** changes. That's why the contracts exist.

---

## 10. Debugging cheatsheet

| Symptom | Fix |
|---|---|
| `FatalTraCIError` / connection closed | SUMO crashed. Run the same `sumo -c ...` command in a terminal to see the error (usually a bad edge id in routes) |
| All lights red or flashing | State string length ≠ `len(links)` |
| Controller seems to do nothing | You're not calling `setRedYellowGreenState`, or you're calling it with the fixed program's own state |
| Lights flicker between phases | Hysteresis too low or min-green not enforced |
| Lots of teleports | Demand too high for the grid. Lower the rush flows |
| Sims get different traffic | Different `--seed` |
| Slow (< 5 steps/s) | Use subscriptions, not per-vehicle getters. Send every 2nd frame |
| `Address already in use` | `lsof -i :8000`, then kill the old server |
| macOS `Library not loaded` | `brew install xerces-c fox proj gdal gl2ps` |

## 11. Docs (for Claude Code lookups)

- Install / pip wheels: https://sumo.dlr.de/docs/Downloads.php
- Grid networks: https://sumo.dlr.de/docs/Networks/Abstract_Network_Generation.html
- TraCI from Python (labels, multiple sims): https://sumo.dlr.de/docs/TraCI/Interfacing_TraCI_from_Python.html
- Traffic light control: https://sumo.dlr.de/docs/TraCI/Change_Traffic_Lights_State.html
- Vehicle values and units: https://sumo.dlr.de/docs/TraCI/Vehicle_Value_Retrieval.html
- Tripinfo and emissions output: https://sumo.dlr.de/docs/Simulation/Output/TripInfo.html
