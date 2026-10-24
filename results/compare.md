# Fixed-time vs CivicSignal (adaptive)

Seeds: 1 · sim length 900 s · ambulance dispatched at t=600 s · mean ± std over seeds, all seeds reported

| Metric | fixed | adaptive | Adaptive vs fixed |
|---|---|---|---|
| Avg delay / vehicle (s, waitingTime) | 27.6 | 12.7 | -53.9% |
| Avg time loss / vehicle (s) | 39.1 | 28.0 | -28.3% |
| Stops / vehicle | 1.2 | 1.8 | +50.7% |
| Total CO₂ (kg) | 179.0 | 176.3 | -1.5% |
| Idling CO₂ (kg) | 38.9 | 17.4 | -55.2% |
| Throughput (vehicles arrived) | 748.0 | 772.0 | +3.2% |
| Teleports | 0.0 | 0.0 | n/a |
| Ambulance trip (s) | 108.0 | 72.0 | -33.3% |

**Adaptive vs fixed: -53.9% delay, -1.5% CO₂ (-55.2% idling CO₂), ambulance -36 s**

## Per seed

| Seed | Controller | Avg delay / vehicle (s, waitingTime) | Avg time loss / vehicle (s) | Stops / vehicle | Total CO₂ (kg) | Idling CO₂ (kg) | Throughput (vehicles arrived) | Teleports | Ambulance trip (s) |
|---|---|---|---|---|---|---|---|---|---|
| 1 | fixed | 27.6 | 39.1 | 1.2 | 179.0 | 38.9 | 748.0 | 0.0 | 108.0 |
| 1 | adaptive | 12.7 | 28.0 | 1.8 | 176.3 | 17.4 | 772.0 | 0.0 | 72.0 |
