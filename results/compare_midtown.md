# Midtown Manhattan: signal strategies compared

Seeds 1, 2, 3 · 2400 s simulated · ambulances dispatched at t = 700, 900, 1100, 1300, 1500 s in every run · CivicSignal runs the Balanced policy (flow 1, climate 1, transit 0.5) · mean ± std over seeds, every seed reported below

| Metric | Fixed-time | Actuated | Green wave | CivicSignal | CivicSignal vs best baseline |
|---|---|---|---|---|---|
| Avg delay / vehicle (s) | 143.1 ± 6.0 | 25.1 ± 0.5 | 51.0 ± 1.5 | **24.1 ± 0.7** | -4.1% vs Actuated |
| Avg time loss / vehicle (s) | 184.8 ± 7.7 | 55.7 ± 0.8 | 74.2 ± 1.6 | **48.8 ± 1.4** | -12.4% vs Actuated |
| Stops / vehicle | 5.86 ± 0.29 | 3.68 ± 0.02 | **2.16 ± 0.02** | 2.68 ± 0.10 | +24.1% vs Green wave |
| Trips completed | 3,532 ± 55 | 3,701 ± 53 | 3,678 ± 49 | **3,708 ± 57** | +0.2% vs Actuated |
| Total CO₂ (kg) | 1,871 ± 58 | 1,135 ± 21 | 1,141 ± 31 | **1,041 ± 30** | -8.3% vs Actuated |
| Idling CO₂ (kg) | 833.4 ± 32.7 | 142.1 ± 1.9 | 295.6 ± 13.5 | **136.8 ± 5.3** | -3.7% vs Actuated |
| Fuel burned ($) | 755.4 ± 23.2 | 458.6 ± 8.4 | 460.5 ± 12.6 | **419.9 ± 12.1** | -8.4% vs Actuated |
| NOx (g) | 705 ± 22 | 391 ± 7 | 409 ± 11 | **360 ± 10** | -8.0% vs Actuated |
| Particulates (g) | 83.1 ± 1.8 | 76.0 ± 1.6 | **72.1 ± 1.5** | 74.2 ± 1.5 | +2.9% vs Green wave |
| Bus trip (s) | 291.8 ± 8.1 | 121.5 ± 2.2 | **83.6 ± 0.4** | 101.1 ± 4.2 | +20.9% vs Green wave |
| Ambulance trip, mean of dispatches (s) | 545.5 ± 25.2 | 255.0 ± 12.2 | 273.5 ± 0.5 | **157.9 ± 4.3** | -38.1% vs Actuated |
| Teleports (gridlock) | 7 ± 3 | 0 | 0 | 0 | n/a vs Actuated |

CivicSignal beats the best baseline on **8 of 11** metrics (bold = best).

**vs Fixed-time: -83.2% delay, -44.3% CO₂, -54.2% stops, ambulance -388 s**

## Every run

| Seed | Strategy | Avg delay / vehicle (s) | Avg time loss / vehicle (s) | Stops / vehicle | Trips completed | Total CO₂ (kg) | Idling CO₂ (kg) | Fuel burned ($) | NOx (g) | Particulates (g) | Bus trip (s) | Ambulance trip, mean of dispatches (s) | Teleports (gridlock) | Ambulance trips (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Fixed-time | 136.9 | 176.4 | 5.5 | 3,525.0 | 1,806.9 | 795.9 | 729.9 | 681.0 | 81.5 | 283.2 | 516.5 | 5.0 | 454, 529, 504, 579 |
| 1 | Actuated | 24.8 | 55.0 | 3.7 | 3,684.0 | 1,123.6 | 139.9 | 453.9 | 387.4 | 75.3 | 119.2 | 266.8 | 0.0 | 290, 249, 276, 267, 252 |
| 1 | Green wave | 50.7 | 73.7 | 2.1 | 3,663.0 | 1,128.8 | 292.0 | 455.7 | 404.9 | 71.4 | 83.7 | 273.4 | 0.0 | 224, 293, 273, 254, 323 |
| 1 | CivicSignal | 23.3 | 47.2 | 2.6 | 3,689.0 | 1,020.2 | 131.5 | 411.4 | 353.0 | 73.5 | 98.7 | 153.0 | 0.0 | 152, 149, 153, 142, 169 |
| 2 | Fixed-time | 143.4 | 186.6 | 6.0 | 3,590.0 | 1,920.0 | 848.1 | 775.2 | 722.4 | 85.1 | 292.8 | 561.4 | 6.0 | 455, 532, 509, 579, 732 |
| 2 | Actuated | 24.8 | 55.4 | 3.7 | 3,761.0 | 1,159.3 | 142.7 | 468.3 | 399.1 | 77.7 | 123.5 | 255.8 | 0.0 | 267, 268, 245, 280, 219 |
| 2 | Green wave | 52.7 | 76.1 | 2.2 | 3,733.0 | 1,176.0 | 310.5 | 474.8 | 422.2 | 73.8 | 84.0 | 273.0 | 0.0 | 222, 292, 273, 253, 325 |
| 2 | CivicSignal | 24.6 | 50.0 | 2.8 | 3,772.0 | 1,075.8 | 142.2 | 433.8 | 371.1 | 75.9 | 98.8 | 160.6 | 0.0 | 154, 146, 143, 173, 187 |
| 3 | Fixed-time | 148.8 | 191.3 | 6.0 | 3,481.0 | 1,884.8 | 856.1 | 761.2 | 712.8 | 82.5 | 299.4 | 558.6 | 10.0 | 459, 524, 503, 485, 822 |
| 3 | Actuated | 25.7 | 56.6 | 3.7 | 3,659.0 | 1,122.9 | 143.6 | 453.5 | 387.2 | 74.8 | 121.9 | 242.4 | 0.0 | 246, 248, 223, 252, 243 |
| 3 | Green wave | 49.7 | 73.0 | 2.2 | 3,639.0 | 1,117.2 | 284.3 | 451.1 | 400.7 | 71.1 | 83.3 | 274.0 | 0.0 | 223, 293, 273, 346, 235 |
| 3 | CivicSignal | 24.4 | 49.1 | 2.7 | 3,662.0 | 1,027.8 | 136.8 | 414.5 | 355.6 | 73.2 | 105.9 | 160.2 | 0.0 | 159, 175, 142, 179, 146 |
