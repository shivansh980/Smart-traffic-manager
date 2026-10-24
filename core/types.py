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
