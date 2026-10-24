# Fixed-time vs CivicSignal (adaptive)

Seeds: 1, 2, 3 · sim length 2400 s · ambulances dispatched at t=700, 900, 1100, 1300, 1500 s (same times in both sims) · mean ± std over seeds, all seeds reported

| Metric | fixed | adaptive | Adaptive vs fixed |
|---|---|---|---|
| Avg delay / vehicle (s, waitingTime) | 35.9 ± 3.2 | 13.7 ± 0.5 | -61.9% |
| Avg time loss / vehicle (s) | 50.9 ± 5.0 | 30.2 ± 0.8 | -40.7% |
| Stops / vehicle | 1.5 ± 0.2 | 1.9 ± 0.0 | +23.6% |
| Total CO₂ (kg) | 634.1 ± 31.6 | 575.5 ± 7.9 | -9.2% |
| Idling CO₂ (kg) | 152.7 ± 14.2 | 56.5 ± 2.1 | -63.0% |
| Throughput (vehicles arrived) | 2744.0 ± 21.7 | 2748.3 ± 17.5 | +0.2% |
| Teleports | 0.0 | 0.0 | n/a |
| Ambulance trip, mean of dispatches (s) | 125.9 ± 12.4 | 78.5 ± 1.8 | -37.6% |

**Adaptive vs fixed: -61.9% delay, -9.2% CO₂ (-63.0% idling CO₂), ambulance -47 s**

Ambulance trips per dispatch (s):

- seed 1 fixed: 104, 83, 146, 129, 113
- seed 1 adaptive: 72, 73, 73, 90, 79
- seed 2 fixed: 115, 88, 156, 134, 123
- seed 2 adaptive: 80, 79, 86, 76, 82
- seed 3 fixed: 117, 92, 235, 130, 123
- seed 3 adaptive: 75, 77, 76, 82, 78

## Per seed

| Seed | Controller | Avg delay / vehicle (s, waitingTime) | Avg time loss / vehicle (s) | Stops / vehicle | Total CO₂ (kg) | Idling CO₂ (kg) | Throughput (vehicles arrived) | Teleports | Ambulance trip, mean of dispatches (s) |
|---|---|---|---|---|---|---|---|---|---|
| 1 | fixed | 39.0 | 55.8 | 1.7 | 667.1 | 166.8 | 2767.0 | 0.0 | 115.0 |
| 1 | adaptive | 14.0 | 31.0 | 1.9 | 584.6 | 58.5 | 2766.0 | 0.0 | 77.4 |
| 2 | fixed | 32.6 | 45.8 | 1.3 | 604.0 | 138.3 | 2741.0 | 0.0 | 123.2 |
| 2 | adaptive | 13.2 | 29.4 | 1.8 | 571.2 | 54.3 | 2748.0 | 0.0 | 80.6 |
| 3 | fixed | 36.2 | 51.3 | 1.5 | 631.2 | 152.9 | 2724.0 | 0.0 | 139.4 |
| 3 | adaptive | 13.8 | 30.3 | 1.9 | 570.6 | 56.9 | 2731.0 | 0.0 | 77.6 |
