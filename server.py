"""FastAPI server: serves web/, streams the sims over /ws, records every frame, hosts the policy copilot.

    python server.py                                   # http://localhost:8000
    python server.py --record recordings/demo.jsonl    # headless backup recording (see --help)
"""
from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import os
import time
import urllib.error
import urllib.request
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.websockets import WebSocketDisconnected

from core.controller import BALANCED, WeightedMaxPressure
from core.sumo_runner import PROGRAMS, SumoRunner
from core.types import Weights

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
RECORDINGS = ROOT / "recordings"
SEED = 1

STRATEGIES = {
    "fixed": {"label": "Fixed-time", "sub": "today's timers"},
    "actuated": {"label": "Actuated", "sub": "detectors extend green"},
    "greenwave": {"label": "Green wave", "sub": "timed progression"},
    "adaptive": {"label": "CivicSignal", "sub": "adaptive, city-steered"},
}


def scenarios() -> dict[str, dict]:
    out = {}
    for meta in sorted((ROOT / "scenario").glob("*/meta.json")):
        m = json.loads(meta.read_text())
        out[m["id"]] = m
    return out


def dumps(obj) -> str:
    return json.dumps(obj, separators=(",", ":"))


class Sim:
    """Several runners stepped in lockstep on the same map and seed, plus the live controls."""

    def __init__(self, scenario: str = "midtown", panes: tuple[str, ...] = ("fixed", "adaptive"), record: bool = True):
        self.weights = Weights(**BALANCED)
        self.record = record
        self.scenario = scenario
        self.panes = list(panes)
        self.playing = False
        self.sps = 10.0
        self.labels = itertools.count()
        self.runners: dict[str, SumoRunner] = {}
        self.rec = None
        self.inspect_tls: str | None = None
        self.follow_vid: str | None = None
        self.start()

    @property
    def meta(self) -> dict:
        return scenarios()[self.scenario]

    def start(self) -> None:
        n = next(self.labels)
        cfg = str(ROOT / self.meta["cfg"])
        for sid in self.panes:
            ctrl = WeightedMaxPressure(self.weights) if sid == "adaptive" else None
            self.runners[sid] = SumoRunner(f"{sid}{n}", cfg, SEED, ctrl, program=PROGRAMS.get(sid, "0"))
        self.pending: list[str] = []
        self.done = False
        self.seen_trips = {sid: 0 for sid in self.panes}
        self.history: list[list] = []   # [t, {pane: [idle CO2, queue]}]
        if self.record:
            RECORDINGS.mkdir(exist_ok=True)
            self.rec = open(RECORDINGS / f"{time.strftime('%Y%m%d-%H%M%S')}-{self.scenario}.jsonl", "w")

    def stop(self) -> None:
        for r in self.runners.values():
            r.close()
        self.runners = {}
        if self.rec is not None:
            self.rec.close()
            self.rec = None

    def restart(self) -> None:
        self.stop()
        self.start()

    @property
    def t(self) -> float:
        return next(iter(self.runners.values())).t if self.runners else 0.0

    def step(self) -> dict:
        events = []
        for ev in self.pending:
            for r in self.runners.values():
                {"ambulance": r.spawn_ambulance, "surge": r.surge, "crash": r.crash}[ev]()
            events.append({"ambulance": "ambulance_spawned", "surge": "surge_started", "crash": "crash_started"}[ev])
        self.pending = []
        sims = {sid: r.step() for sid, r in self.runners.items()}
        for sid, r in self.runners.items():
            if len(r.amb_trips) > self.seen_trips[sid]:
                self.seen_trips[sid] = len(r.amb_trips)
                events.append(f"ambulance_arrived_{sid}")
        t = self.t
        self.history.append([t, {sid: [s["m"]["idle_co2_kg"], s["m"]["queue"]] for sid, s in sims.items()}])
        if t >= self.meta["end"]:
            self.done, self.playing = True, False
            events.append("sim_end")
        frame = {"type": "frame", "t": t, "scenario": self.scenario, "sims": sims, "events": events}
        if self.inspect_tls:
            frame["inspect"] = {sid: r.inspect(self.inspect_tls) for sid, r in self.runners.items()}
        if self.follow_vid:
            frame["follow"] = {"vid": self.follow_vid, **{sid: r.trip(self.follow_vid) for sid, r in self.runners.items()}}
        if self.rec is not None:
            self.rec.write(dumps(frame) + "\n")
        return frame

    def apply(self, msg: dict) -> bool:
        """Apply a browser message. Returns True if the sims were restarted."""
        kind = msg.get("type")
        if kind == "weights":
            for k in ("flow", "climate", "transit", "fairness"):
                if k in msg:
                    setattr(self.weights, k, float(msg[k]))
            if "preempt" in msg:
                self.weights.preempt = bool(msg["preempt"])
        elif kind == "ambulance":
            self.pending.append("ambulance")
        elif kind == "event" and msg.get("name") in ("ambulance", "surge", "crash"):
            self.pending.append(msg["name"])
        elif kind == "inspect":
            self.inspect_tls = msg.get("tls") or None
        elif kind == "follow":
            self.follow_vid = msg.get("vid") or None
        elif kind == "control":
            action = msg.get("action")
            if action == "play" and not self.done:
                self.playing = True
            elif action == "pause":
                self.playing = False
            elif action == "reset":
                self.playing = False
                self.restart()
                return True
        elif kind == "speed":
            self.sps = max(1.0, min(200.0, float(msg.get("sps", 10))))
        elif kind == "config":
            scen = msg.get("scenario", self.scenario)
            panes = [p for p in msg.get("panes", self.panes) if p in STRATEGIES][:4] or self.panes
            if scen in scenarios():
                self.playing = False
                self.stop()
                self.scenario, self.panes, self.inspect_tls, self.follow_vid = scen, panes, None, None
                self.start()
                return True
        return False

    def state(self) -> dict:
        return {"type": "state", "weights": asdict(self.weights), "playing": self.playing, "sps": self.sps,
                "t": self.t, "done": self.done, "scenario": self.scenario, "panes": self.panes,
                "scenarios": {k: {x: v[x] for x in ("title", "subtitle", "rush", "end")} for k, v in scenarios().items()},
                "strategies": STRATEGIES, "balanced": BALANCED, "copilot": bool(gemini_key()),
                "inspect": self.inspect_tls, "follow": self.follow_vid}


# ------------------------------------------------------------------ policy copilot (Gemini)

def gemini_key() -> str | None:
    key = os.environ.get("GEMINI_API_KEY")
    env = ROOT / ".env"
    if not key and env.exists():
        for line in env.read_text().splitlines():
            if line.strip().startswith("GEMINI_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
    return key or None


_model: str | None = os.environ.get("GEMINI_MODEL")


def _gemini(path: str, body: dict | None = None) -> dict:
    url = f"https://generativelanguage.googleapis.com/v1beta/{path}"
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body else None,
                                 headers={"Content-Type": "application/json", "x-goog-api-key": gemini_key() or ""})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def gemini_model() -> str:
    """Pick the newest Flash model this key can call, once."""
    global _model
    if _model:
        return _model
    models = _gemini("models?pageSize=200").get("models", [])
    flash = [m["name"] for m in models if "generateContent" in m.get("supportedGenerationMethods", [])
             and "flash" in m["name"] and "lite" not in m["name"] and "preview" not in m["name"]
             and "exp" not in m["name"] and "image" not in m["name"] and "tts" not in m["name"]]
    _model = sorted(flash)[-1].removeprefix("models/") if flash else "gemini-2.5-flash"
    return _model


COPILOT_PROMPT = """You are the policy copilot for CivicSignal, an adaptive traffic-signal system a city can steer.
A city official describes a goal in plain English. Translate it into the controller's four priority weights and
explain the trade-off honestly in 2-3 short sentences a resident would understand.

Weights (each 0.0 to 3.0):
- flow: move the most vehicles (queue pressure). Keep at least 0.5 unless told to ignore throughput.
- climate: keep moving platoons moving; fewer stop-and-go restarts means less CO2 and fuel.
- transit: give buses priority at lights.
- fairness: cap the longest wait so no driver or side street is starved.
preempt (true/false): emergency vehicles get green corridors. Only turn it off if explicitly asked.
You may also suggest one event to simulate if the request describes one: "ambulance", "surge" (a crowd leaving a
venue), "crash" (lanes blocked), or "none".

Measured effects in our simulations, to keep claims honest: climate cuts stops ~30-40% and CO2 ~10%; transit cuts
bus waiting ~25%; fairness cuts the longest waits ~40%; preemption cuts ambulance trips ~40%.
Current map: {scenario}. Current weights: {weights}.
"""

COPILOT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "flow": {"type": "NUMBER"}, "climate": {"type": "NUMBER"}, "transit": {"type": "NUMBER"},
        "fairness": {"type": "NUMBER"}, "preempt": {"type": "BOOLEAN"},
        "event": {"type": "STRING", "enum": ["ambulance", "surge", "crash", "none"]},
        "title": {"type": "STRING"}, "explanation": {"type": "STRING"},
    },
    "required": ["flow", "climate", "transit", "fairness", "preempt", "event", "title", "explanation"],
}


def copilot(text: str, scenario: str, weights: dict) -> dict:
    body = {
        "systemInstruction": {"parts": [{"text": COPILOT_PROMPT.format(scenario=scenario, weights=json.dumps(weights))}]},
        "contents": [{"role": "user", "parts": [{"text": text[:1000]}]}],
        "generationConfig": {"responseMimeType": "application/json", "responseSchema": COPILOT_SCHEMA,
                             "temperature": 0.2},
    }
    out = _gemini(f"models/{gemini_model()}:generateContent", body)
    plan = json.loads(out["candidates"][0]["content"]["parts"][0]["text"])
    for k in ("flow", "climate", "transit", "fairness"):
        plan[k] = round(max(0.0, min(3.0, float(plan[k]))) * 4) / 4
    plan["model"] = gemini_model()
    return plan


# ------------------------------------------------------------------ app

sim: Sim | None = None
clients: set[WebSocket] = set()
lock = asyncio.Lock()            # sim stepping and restarts never overlap
last_frame: str | None = None
loop_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(_app):
    yield
    if loop_task is not None:
        loop_task.cancel()
    if sim is not None:
        sim.stop()


app = FastAPI(lifespan=lifespan)


@app.post("/api/copilot")
async def api_copilot(payload: dict):
    if not gemini_key():
        return JSONResponse({"error": "No GEMINI_API_KEY in .env"}, status_code=503)
    weights = asdict(sim.weights) if sim else BALANCED
    scen = sim.meta["title"] if sim else "Midtown Manhattan"
    try:
        return await asyncio.to_thread(copilot, str(payload.get("text", "")), scen, weights)
    except urllib.error.HTTPError as e:
        return JSONResponse({"error": f"Gemini HTTP {e.code}: {e.read()[:300].decode(errors='ignore')}"}, status_code=502)
    except Exception as e:  # network down, bad JSON: the UI shows the message and the sliders still work
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=502)


async def send(ws: WebSocket, text: str) -> None:
    try:
        await asyncio.wait_for(ws.send_text(text), timeout=5)
    except Exception:
        clients.discard(ws)


async def broadcast(text: str) -> None:
    await asyncio.gather(*(send(ws, text) for ws in list(clients)))


def snapshot() -> list[str]:
    return [dumps(sim.state()), dumps({"type": "history", "scenario": sim.scenario, "points": sim.history})]


async def sim_loop() -> None:
    """The one place the sims advance; every connected window gets every frame."""
    global last_frame
    while True:
        if sim.playing and not sim.done and clients:
            t0 = time.perf_counter()
            async with lock:
                last_frame = dumps(sim.step())
                done = sim.done
            await broadcast(last_frame)
            if done:
                await broadcast(dumps(sim.state()))
            await asyncio.sleep(max(0.0, 1 / sim.sps - (time.perf_counter() - t0)))
        else:
            await asyncio.sleep(0.05)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    global sim, last_frame, loop_task
    await ws.accept()
    async with lock:
        if sim is None:
            sim = await asyncio.to_thread(Sim)
        if last_frame is None:
            last_frame = dumps(sim.step())
    if loop_task is None:
        loop_task = asyncio.create_task(sim_loop())
    for text in snapshot() + [last_frame]:
        await ws.send_text(text)
    clients.add(ws)
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            async with lock:
                restarted = await asyncio.to_thread(sim.apply, msg)
                if restarted:
                    last_frame = dumps(sim.step())   # one frame so every window redraws the new map
            if restarted:
                for text in snapshot() + [last_frame]:
                    await broadcast(text)
            else:
                await broadcast(dumps(sim.state()))
    except (WebSocketDisconnect, WebSocketDisconnected):
        pass
    finally:
        clients.discard(ws)
        if not clients and sim is not None:
            sim.playing = False


RECORDINGS.mkdir(exist_ok=True)
app.mount("/recordings", StaticFiles(directory=RECORDINGS), name="recordings")
app.mount("/", StaticFiles(directory=WEB, html=True), name="web")


def record(path: str, scenario: str, panes: list[str], end: int, script: dict[int, str], every: int) -> None:
    """Headless deterministic recording for the replay backup. script: {sim second: event}."""
    s = Sim(scenario, tuple(panes), record=False)
    end = min(end, s.meta["end"])
    with open(path, "w") as fh:
        fh.write(dumps(s.state()) + "\n")
        while not s.done and s.t < end:
            if int(s.t) in script:
                s.apply({"type": "event", "name": script[int(s.t)]})
            frame = s.step()
            if int(frame["t"]) % every == 0 or frame["events"]:
                fh.write(dumps(frame) + "\n")
    s.stop()
    print(f"wrote {path} ({Path(path).stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", help="write a headless replay to this .jsonl path and exit")
    ap.add_argument("--scenario", default="midtown")
    ap.add_argument("--panes", default="fixed,adaptive")
    ap.add_argument("--end", type=int, default=2400)
    ap.add_argument("--every", type=int, default=1, help="keep every Nth frame (smaller file)")
    ap.add_argument("--events", default="950:ambulance",
                    help="comma list of second:event, e.g. 700:surge,950:ambulance,1100:crash")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    if args.record:
        script = {int(k): v for k, v in (x.split(":") for x in args.events.split(",") if x)}
        record(args.record, args.scenario, args.panes.split(","), args.end, script, args.every)
    else:
        import uvicorn
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
