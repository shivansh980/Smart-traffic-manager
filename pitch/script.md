# CivicSignal: 2-minute pitch

All numbers come from `results/compare.md` (3 seeds, all reported) or from the preset runs noted below.

## Before you go on

1. `python server.py`, then open <http://localhost:8000> in Chrome, full screen (⌃⌘F).
2. Set speed to 10× and press Space. At about **9:00** sim time, press Space to pause and set speed to **1×**.
3. In a second tab, open the backup: <http://localhost:8000/?replay=/recordings/demo.jsonl&t=540>
4. Close Docker, Slack, and extra tabs. Check Activity Monitor: memory pressure should be green.

If the live sim misbehaves, switch tabs to the replay and keep talking. It plays the same story, with the
ambulance dispatched at 15:50.

## Script (about 2:00)

**Hook (0:00–0:15)**
"Every red light over an empty intersection costs you time and burns fuel while you idle. Many signals still run
on fixed timers. They don't know whether anyone is waiting."

**Side by side (0:15–0:45)** *Press Space. Rush hour starts at 10:00.*
"Same nine intersections, same cars, same random seed. Left: today's fixed timer. Right: CivicSignal. Every light
reads its queues (data loop detectors and cameras already collect) and gives green where the pressure is highest.
Watch the left side back up as rush hour hits." *Point at the cards:* "Average delay is down by more than half, and so
is the wasted idling CO₂."

**Ambulance (0:45–1:10)** *Press A at about 11:00 to 12:00 sim time.*
"Same ambulance, same route, same second, in both cities. On the right, every light ahead on its route turns green
early enough to flush its queue. It never skips a yellow." *Wait for both arrival toasts (about 13 s at 1×).*
"Across 15 dispatches: **78 seconds with CivicSignal, 126 with fixed timers.** And fixed timers are a lottery:
anywhere from 83 to 235 seconds."

**Civics (1:10–1:40)**
"Cities shouldn't get a black box. These sliders are the city's values, written into the controller."
*Click **Fairness**:* "Fairness caps the longest wait. Watch 'Longest wait right now'. In our runs it cuts the
typical longest wait by 40%." *Click **Transit**:* "Transit puts buses first: 24 to 30% less bus waiting, with no
cost to everyone else."
"Every decision is a formula you can read and audit. The city chooses its values; the lights carry them out."

**Results (1:40–2:00)**
"Three seeds, all reported: **−62% delay, −63% idling CO₂, −9% total CO₂, and the ambulance arrives 47 seconds
sooner**, with the same throughput and zero gridlock. It runs on detectors cities already own and on a small box
in the signal cabinet."

## Judge Q&A

- **Is the baseline a strawman?** It's SUMO's default fixed-time program: a 90 s cycle with an even split, the most
  common real-world setup. We haven't benchmarked against actuated control, and we say so.
- **Why max-pressure, not RL?** It needs no training data and has throughput-optimality results in the literature
  (Varaiya 2013). Every decision is auditable: it's one line of arithmetic per light. That's the civics point.
- **Downsides?** Cars stop more often (+24% stops per vehicle) but for much less time: time loss is −41%. Total CO₂
  falls less than idling CO₂ (−9% vs −63%) because stop-and-go acceleration costs fuel too.
- **Does it only work on your demand?** Gains are biggest when demand is uneven (here, rush hour on one axis at 3× the
  cross streets). That's the normal case downtown. Under perfectly uniform demand a good fixed timer is hard to beat.
- **Deployment?** Queue counts come from existing loop detectors or cameras, and the controller runs on an edge box in
  the cabinet. Min-green (8 s), max-green (60 s), yellow (3 s), and all-red (1 s) bounds keep it safe.
  Emergency vehicles would broadcast their approach, which is how today's preemption systems work.
- **Is the ambulance demo cherry-picked?** No. The table averages 5 dispatch times × 3 seeds. The recorded demo uses
  a dispatch where the fixed-time trip (126 s) is near its median, not the worst case.

Preset numbers (Fairness, Transit) come from full-length runs on seeds 1 and 2, compared against the default
weights.
