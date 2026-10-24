# Demo grid: signal strategies compared

Seeds 1, 2, 3 · 2400 s simulated · ambulances dispatched at t = 700, 900, 1100, 1300, 1500 s in every run · CivicSignal runs the Balanced policy (flow 1, climate 1, transit 0.5) · mean ± std over seeds, every seed reported below

| Metric | Fixed-time | Actuated | Green wave | CivicSignal | CivicSignal vs best baseline |
|---|---|---|---|---|---|
| Avg delay / vehicle (s) | 35.9 ± 3.2 | **7.2 ± 0.2** | 28.5 ± 0.3 | 11.7 ± 0.1 | +61.9% vs Actuated |
| Avg time loss / vehicle (s) | 50.9 ± 5.0 | **20.8 ± 0.4** | 42.6 ± 0.5 | 24.8 ± 0.2 | +19.2% vs Actuated |
| Stops / vehicle | 1.51 ± 0.17 | **1.29 ± 0.03** | 1.33 ± 0.02 | 1.36 ± 0.01 | +5.7% vs Actuated |
| Trips completed | 2,744 ± 22 | **2,758 ± 18** | 2,739 ± 23 | 2,751 ± 20 | -0.2% vs Actuated |
| Total CO₂ (kg) | 634 ± 32 | **522 ± 7** | 602 ± 5 | 528 ± 6 | +1.1% vs Actuated |
| Idling CO₂ (kg) | 152.7 ± 14.2 | **29.6 ± 0.8** | 120.7 ± 1.6 | 48.5 ± 0.5 | +64.0% vs Actuated |
| Fuel burned ($) | 255.7 ± 12.6 | **210.8 ± 2.8** | 242.8 ± 2.2 | 212.9 ± 2.4 | +1.0% vs Actuated |
| NOx (g) | 235 ± 11 | **186 ± 2** | 220 ± 2 | 189 ± 2 | +1.3% vs Actuated |
| Particulates (g) | 49.8 ± 0.7 | 49.3 ± 0.4 | **48.9 ± 0.4** | 48.9 ± 0.3 | +0.1% vs Green wave |
| Bus trip (s) | 106.2 ± 1.8 | 77.3 ± 2.7 | 84.9 ± 0.2 | **70.8 ± 2.4** | -8.4% vs Actuated |
| Ambulance trip, mean of dispatches (s) | 125.9 ± 12.4 | 117.2 ± 2.6 | 157.6 ± 14.2 | **78.3 ± 2.5** | -33.2% vs Actuated |
| Teleports (gridlock) | 0 | 0 | 0 | 0 | n/a vs Fixed-time |

CivicSignal beats the best baseline on **2 of 11** metrics (bold = best).

**vs Fixed-time: -67.3% delay, -16.7% CO₂, -9.9% stops, ambulance -48 s**

## Every run

| Seed | Strategy | Avg delay / vehicle (s) | Avg time loss / vehicle (s) | Stops / vehicle | Trips completed | Total CO₂ (kg) | Idling CO₂ (kg) | Fuel burned ($) | NOx (g) | Particulates (g) | Bus trip (s) | Ambulance trip, mean of dispatches (s) | Teleports (gridlock) | Ambulance trips (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Fixed-time | 39.0 | 55.8 | 1.7 | 2,767.0 | 667.1 | 166.8 | 268.8 | 246.2 | 50.7 | 107.5 | 115.0 | 0.0 | 104, 83, 146, 129, 113 |
| 1 | Actuated | 7.4 | 21.3 | 1.3 | 2,775.0 | 530.4 | 30.3 | 214.0 | 189.0 | 49.8 | 78.3 | 115.0 | 0.0 | 122, 105, 106, 128, 114 |
| 1 | Green wave | 28.3 | 42.3 | 1.3 | 2,765.0 | 604.9 | 121.1 | 244.2 | 221.9 | 49.3 | 85.1 | 172.8 | 0.0 | 186, 166, 148, 167, 197 |
| 1 | CivicSignal | 11.8 | 25.1 | 1.4 | 2,773.0 | 534.5 | 49.0 | 215.4 | 190.7 | 49.3 | 68.7 | 77.6 | 0.0 | 76, 73, 72, 89, 78 |
| 2 | Fixed-time | 32.6 | 45.8 | 1.3 | 2,741.0 | 604.0 | 138.3 | 243.7 | 223.8 | 49.3 | 104.2 | 123.2 | 0.0 | 115, 88, 156, 134, 123 |
| 2 | Actuated | 7.1 | 20.5 | 1.3 | 2,759.0 | 518.4 | 28.7 | 209.3 | 185.0 | 49.2 | 74.2 | 116.6 | 0.0 | 108, 113, 106, 129, 127 |
| 2 | Green wave | 28.9 | 43.1 | 1.4 | 2,730.0 | 604.6 | 122.0 | 243.9 | 220.9 | 48.8 | 84.9 | 144.6 | 0.0 | 137, 166, 147, 127, 146 |
| 2 | CivicSignal | 11.6 | 24.7 | 1.4 | 2,746.0 | 527.3 | 48.1 | 212.5 | 188.3 | 48.9 | 73.5 | 81.0 | 0.0 | 80, 79, 87, 80, 79 |
| 3 | Fixed-time | 36.2 | 51.3 | 1.5 | 2,724.0 | 631.2 | 152.9 | 254.6 | 233.9 | 49.4 | 106.8 | 139.4 | 0.0 | 117, 92, 235, 130, 123 |
| 3 | Actuated | 7.3 | 20.8 | 1.3 | 2,739.0 | 518.0 | 29.7 | 209.1 | 185.3 | 49.0 | 79.3 | 120.0 | 0.0 | 130, 119, 96, 141, 114 |
| 3 | Green wave | 28.2 | 42.2 | 1.3 | 2,721.0 | 595.6 | 118.9 | 240.2 | 218.1 | 48.6 | 84.8 | 155.4 | 0.0 | 139, 167, 147, 178, 146 |
| 3 | CivicSignal | 11.8 | 24.7 | 1.3 | 2,735.0 | 522.7 | 48.5 | 210.7 | 187.4 | 48.6 | 70.3 | 76.2 | 0.0 | 79, 78, 75, 75, 74 |
