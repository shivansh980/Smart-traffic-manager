# CivicSignal: 2-minute video script and shot list

All numbers come from `results/compare_midtown.md` (3 seeds, 40-minute rush hour, every seed reported).
Record each shot separately, then cut them together. Retakes are free, and nothing has to work live.

## Setup (once)

1. `python server.py`, then open <http://localhost:8000> in Chrome. Hide the bookmarks bar and full-screen the
   window (⌃⌘F). 1440×900 or 1512×982 looks right.
2. Record with ⌘⇧5 → "Record selected portion" over the browser, or QuickTime. Turn on "show mouse clicks".
3. To jump to rush hour for any shot: set speed to 10×, press Space, and pause (Space) at about 9:00 sim time.
   Then set 1× or 2× before recording.
4. Close Slack, Docker and extra tabs. Four Manhattans at once is the heaviest view.

## Shots

**1. Hook (0:00–0:15).** *Compare: All four strategies, paused at about 9:30, Impact tab.*
> "These are 54 real traffic lights in Midtown Manhattan, 6th to 3rd Avenue. NYC already watches these blocks with
> sensors, and engineers retime them from a control room. We asked: what if every light decided for itself every
> second, by priorities the city sets in public?"

**2. Four cities, same traffic (0:15–0:40).** *Press Space at 2×. Let rush hour build. Press H for the heatmap.*
> "Same cars, same second, four ways to run the lights: today's fixed timers, detector-actuated lights, a coordinated
> green wave, and CivicSignal. Watch fixed-time back up and glow with exhaust." *Point at the Impact table as stars
> move to CivicSignal.*

**3. Ambulance race (0:40–1:00).** *Events tab → 🚑 Dispatch ambulance (or press A). Keep 1× so the race is readable.*
> "An ambulance heads for Mount Sinai West, same route in all four cities. CivicSignal sees it coming and turns
> every light on its route green early enough to flush the queue, and it never skips a yellow." *Wait for the race
> bars to finish.* "Across 15 dispatches: 2:38 with CivicSignal, 4:15 with the best alternative, over 9 minutes on
> fixed timers."

**4. Chaos (1:00–1:15).** *Press S (Radio City surge), then C (crash at St. Patrick's).*
> "A Radio City show lets out, and a crash blocks two lanes of 5th Avenue. Fixed timers just keep counting.
> CivicSignal reroutes green time to where the queues are."

**5. The city steers (1:15–1:40).** *Policy tab. Type into the copilot:* "Radio City lets out at 10pm. Keep 6th Ave
moving, protect the buses, and don't let side streets wait forever." *→ Ask copilot → Apply policy.*
*Then click any intersection on the CivicSignal map → Inspect tab.*
> "Cities shouldn't get a black box. An official writes the goal in plain English, and the copilot only sets four
> public dials. The lights still run on one auditable formula. Click any intersection and you see exactly why it's
> green: queue pressure, platoons, buses, waiting time."

**6. Results (1:40–2:00).** *Impact tab, all four strategies, late in the run. Or cut to the README results table.*
> "Over three full rush hours, CivicSignal beats the best of today's methods on 8 of 11 measures: 4% less delay,
> 8% less CO₂, fuel and smog, and 38% faster ambulances. Against fixed timers: 83% less delay and 44% less CO₂.
> The green wave still wins on stops and buses, and we show that too. CivicSignal: traffic lights the city can steer."

## If you're short on time

Use only shots 2, 3 and 6, in Fixed-time vs CivicSignal mode, which runs the lightest.

## Judge Q&A

- **Is the baseline a strawman?** We tested against three: SUMO's fixed-time program, detector-actuated control
  (gap-out, 6–55 s greens), and a green wave with avenue-weighted splits and travel-time offsets. Actuated is strong:
  it beats us on delay on the 3×3 demo grid (7.2 s vs 11.7 s), and we say so.
- **Why max-pressure, not RL?** It needs no training data and has throughput-optimality results (Varaiya 2013).
  Every decision is one line of arithmetic per light, which is the civics point.
- **Where do you lose?** The green wave has fewer stops (2.16 vs 2.68 per vehicle) and faster buses (84 vs 101 s) on
  Manhattan's avenues. The Climate and Transit dials narrow that gap when the city wants them to.
- **What was hard?** Real map data. OpenStreetMap splits some approaches into 12 m segments, so a light only saw the
  last car or two and starved Madison Ave. We added advance detection: each light counts its whole approach, like
  real loop detectors. That took one seed from 38 s to 25 s of delay.
- **Deployment?** Queue counts come from detectors and cameras NYC already has in this zone ("Midtown in Motion",
  2011: microwave sensors, cameras and E-ZPass readers, with timing adjusted remotely, and DOT reported 10% faster
  travel). CivicSignal runs per intersection on a cabinet computer, with min-green, max-green, yellow and all-red
  bounds for safety.
- **Is the ambulance cherry-picked?** No. Five dispatch times per run × three seeds, all averaged and all listed in
  `results/compare_midtown.md`.

Sources for the NYC facts: NYC DOT press release (2012),
<https://www.nyc.gov/html/dot/html/pr2012/pr12_25.shtml>; ITS JPO summary, <https://www.itskrs.its.dot.gov/2012-l00639>.
