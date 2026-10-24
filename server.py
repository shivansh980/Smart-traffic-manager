"""FastAPI server: serves web/, streams both sims over /ws, records every frame (spec 5.5).

    python server.py                                  # http://localhost:8000
    python server.py --record recordings/demo.jsonl   # headless backup recording, no browser needed
"""
from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from starlette.websockets import WebSocketDisconnected

from core.controller import WeightedMaxPressure
from core.sumo_runner import SumoRunner
from core.types import Weights

ROOT = Path(__file__).resolve().parent
CFG = str(ROOT / "scenario" / "sim.sumocfg")
WEB = ROOT / "web"
RECORDINGS = ROOT / "recordings"
SEED = 1
END = 2400


def dumps(obj) -> str:
    return json.dumps(obj, separators=(",", ":"))


class Sim:
    """Both runners stepped in lockstep, plus the live controls."""

    def __init__(self, record: bool = True):
        self.weights = Weights()
        self.record = record
        self.playing = False
        self.sps = 10.0
        self.labels = itertools.count()
        self.fixed = self.adaptive = None
        self.rec = None
        self.start()

    def start(self) -> None:
        n = next(self.labels)
        self.fixed = SumoRunner(f"fixed{n}", CFG, SEED, None)
        self.adaptive = SumoRunner(f"adaptive{n}", CFG, SEED, WeightedMaxPressure(self.weights))
        self.pending_amb = False
        self.done = False
        self.seen_trips = {"fixed": 0, "adaptive": 0}
        self.history: list[list[float]] = []   # [t, fixed idle CO2, adaptive idle CO2, fixed queue, adaptive queue]
        if self.record:
            RECORDINGS.mkdir(exist_ok=True)
            self.rec = open(RECORDINGS / f"{time.strftime('%Y%m%d-%H%M%S')}.jsonl", "w")

    def stop(self) -> None:
        for r in (self.fixed, self.adaptive):
            if r is not None:
                r.close()
        if self.rec is not None:
            self.rec.close()
            self.rec = None

    def reset(self) -> None:
        self.stop()
        self.start()

    def step(self) -> dict:
        events = []
        if self.pending_amb:
            self.fixed.spawn_ambulance()
            self.adaptive.spawn_ambulance()
            self.pending_amb = False
            events.append("ambulance_spawned")
        sims = {"fixed": self.fixed.step(), "adaptive": self.adaptive.step()}
        for name, runner in (("fixed", self.fixed), ("adaptive", self.adaptive)):
            if len(runner.amb_trips) > self.seen_trips[name]:
                self.seen_trips[name] = len(runner.amb_trips)
                events.append(f"ambulance_arrived_{name}")
        t = sims["fixed"]["m"]["t"]
        fm, am = sims["fixed"]["m"], sims["adaptive"]["m"]
        self.history.append([t, fm["idle_co2_kg"], am["idle_co2_kg"], fm["queue"], am["queue"]])
        if t >= END:
            self.done, self.playing = True, False
            events.append("sim_end")
        frame = {"type": "frame", "t": t, "sims": sims, "events": events}
        if self.rec is not None:
            self.rec.write(dumps(frame) + "\n")
        return frame

    def apply(self, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "weights":
            for k in ("flow", "climate", "transit", "fairness"):
                if k in msg:
                    setattr(self.weights, k, float(msg[k]))
            if "preempt" in msg:
                self.weights.preempt = bool(msg["preempt"])
        elif kind == "ambulance":
            self.pending_amb = True
        elif kind == "control":
            action = msg.get("action")
            if action == "play" and not self.done:
                self.playing = True
            elif action == "pause":
                self.playing = False
            elif action == "reset":
                self.playing = False
                self.reset()
        elif kind == "speed":
            self.sps = max(1.0, min(200.0, float(msg.get("sps", 10))))

    def state(self) -> dict:
        return {"type": "state", "weights": asdict(self.weights), "playing": self.playing,
                "sps": self.sps, "t": self.fixed.t, "done": self.done}


sim: Sim | None = None
active: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(_app):
    yield
    if sim is not None:
        sim.stop()


app = FastAPI(lifespan=lifespan)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    global sim, active
    await ws.accept()
    if sim is None:
        sim = Sim()
    if active is not None:          # one viewer drives the sim; a new tab takes over
        active.cancel()
    active = asyncio.current_task()

    async def reader():
        while True:
            msg = json.loads(await ws.receive_text())
            was_reset = msg.get("type") == "control" and msg.get("action") == "reset"
            sim.apply(msg)
            if was_reset:
                await ws.send_text(dumps(sim.step()))   # one frame so the UI clears
            await ws.send_text(dumps(sim.state()))

    async def writer():
        await ws.send_text(dumps(sim.state()))
        await ws.send_text(dumps({"type": "history", "points": sim.history}))   # a reloaded page keeps its chart
        await ws.send_text(dumps(sim.step()))           # first frame so the UI has something to draw
        while True:
            if sim.playing and not sim.done:
                t0 = time.perf_counter()
                frame = sim.step()
                await ws.send_text(dumps(frame))
                if sim.done:
                    await ws.send_text(dumps(sim.state()))
                await asyncio.sleep(max(0.0, 1 / sim.sps - (time.perf_counter() - t0)))
            else:
                await asyncio.sleep(0.05)

    tasks = [asyncio.create_task(reader()), asyncio.create_task(writer())]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for t in done:
            if t.exception() and not isinstance(t.exception(), (WebSocketDisconnect, WebSocketDisconnected)):
                raise t.exception()
    except asyncio.CancelledError:
        pass
    finally:
        for t in tasks:
            t.cancel()
        if sim is not None:
            sim.playing = False


app.mount("/recordings", StaticFiles(directory=RECORDINGS), name="recordings")
app.mount("/", StaticFiles(directory=WEB, html=True), name="web")


def record(path: str, end: int, amb_t: int) -> None:
    """Headless deterministic recording for the replay backup: ambulance at amb_t, default weights."""
    s = Sim(record=False)
    with open(path, "w") as fh:
        while not s.done and s.fixed.t < end:
            if s.fixed.t == amb_t:
                s.apply({"type": "ambulance"})
            fh.write(dumps(s.step()) + "\n")
    s.stop()
    print(f"wrote {path} ({Path(path).stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", help="write a headless replay to this .jsonl path and exit")
    ap.add_argument("--end", type=int, default=END)
    ap.add_argument("--amb", type=int, default=950,
                    help="ambulance dispatch time for --record (950: fixed-time trip near its median, not a worst case)")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    if args.record:
        record(args.record, args.end, args.amb)
    else:
        import uvicorn
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
