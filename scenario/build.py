"""Build the scenarios: SUMO net, routes, signal programs, sumocfg, meta, and the browser's map file.

    python scenario/build.py            # all scenarios
    python scenario/build.py midtown    # one

Each scenario lands in scenario/<id>/ (sim.sumocfg, tls.add.xml, meta.json, ...) and web/scenarios/<id>.json.
Signal programs written to tls.add.xml, selected at runtime by the runner:
    "0"          SUMO's default fixed-time program (even split, 90 s cycle)
    "actuated"   same phases, gap-out actuated control on auto-generated detectors
    "greenwave"  fixed-time with a major-axis split and offsets for progression along the major axis
"""
from __future__ import annotations

import json
import math
import random
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import sumo
import sumolib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
WEB = ROOT / "web" / "scenarios"
END = 2400
RUSH = (600, 1800)
CYCLE = 90
YELLOW = 3
WAVE_MAJOR_GREEN = 52          # green-wave split: major axis 52 s, minor 32 s, two 3 s yellows = 90 s
WAVE_SPEED = 10.0              # m/s progression speed for green-wave offsets
NYC_SPEED = 11.18              # 25 mph


# ------------------------------------------------------------------ shared helpers

def fringe(net) -> tuple[list, list]:
    """Sources/sinks: edges leaving/entering a non-signalized dead-end node (one neighbour)."""
    sources, sinks = [], []
    for n in net.getNodes():
        if n.getType() == "traffic_light":
            continue
        neigh = {e.getToNode().getID() for e in n.getOutgoing()} | {e.getFromNode().getID() for e in n.getIncoming()}
        if len(neigh) == 1:
            sources += n.getOutgoing()
            sinks += n.getIncoming()
    return sources, sinks


def green_states(states: list[str]) -> list[str]:
    return list(dict.fromkeys(s for s in states if any(c in "Gg" for c in s) and "y" not in s))


def yellow_between(cur: str, nxt: str) -> str:
    return "".join("y" if c in "Gg" and n not in "Gg" else c for c, n in zip(cur, nxt))


def write_tls_programs(net, path: Path, is_major) -> dict:
    """Actuated and green-wave programs for every light with >= 2 green states. Returns stats."""
    root = ET.Element("additional")
    n_wave = 0
    for tls in net.getTrafficLights():
        prog = tls.getPrograms()["0"]
        phases = prog.getPhases()
        greens = green_states([p.state for p in phases])
        if len(greens) < 2:
            continue
        links = {}
        for in_lane, out_lane, idx in tls.getConnections():
            links[idx] = in_lane
        n_links = len(phases[0].state)

        act = ET.SubElement(root, "tlLogic", id=tls.getID(), type="actuated", programID="actuated", offset="0")
        ET.SubElement(act, "param", key="max-gap", value="3.0")
        ET.SubElement(act, "param", key="detector-gap", value="2.0")
        for p in phases:
            if p.state in greens:
                ET.SubElement(act, "phase", duration=str(int(p.duration)), minDur="6", maxDur="55", state=p.state)
            else:
                ET.SubElement(act, "phase", duration=str(int(p.duration)), state=p.state)

        # green wave: major green gets the bigger split; offset = travel time along the major direction
        major_idx = [i for i in range(n_links) if i in links and is_major(links[i].getEdge())]
        if len(greens) == 2 and major_idx:
            major = max(greens, key=lambda g: sum(g[i] in "Gg" for i in major_idx))
            minor = next(g for g in greens if g != major)
            minor_green = CYCLE - WAVE_MAJOR_GREEN - 2 * YELLOW
            seq = [(major, WAVE_MAJOR_GREEN), (yellow_between(major, minor), YELLOW),
                   (minor, minor_green), (yellow_between(minor, major), YELLOW)]
            in_edges = [links[i].getEdge() for i in major_idx]
            u = wave_direction(in_edges)
            x, y = tls_coord(tls)
            offset = int(round((x * u[0] + y * u[1]) / WAVE_SPEED)) % CYCLE
            n_wave += 1
        else:
            seq, offset = [(p.state, int(p.duration)) for p in phases], 0
        wave = ET.SubElement(root, "tlLogic", id=tls.getID(), type="static", programID="greenwave", offset=str(offset))
        for state, dur in seq:
            ET.SubElement(wave, "phase", duration=str(dur), state=state)
    ET.indent(root)
    path.write_text(ET.tostring(root, encoding="unicode") + "\n")
    return {"greenwave_lights": n_wave}


def wave_direction(in_edges) -> tuple[float, float]:
    """Unit travel direction for progression. Two-way roads pick the +y (or +x) direction."""
    vecs = []
    for e in in_edges:
        (x0, y0), (x1, y1) = e.getFromNode().getCoord(), e.getToNode().getCoord()
        d = math.hypot(x1 - x0, y1 - y0) or 1
        vecs.append(((x1 - x0) / d, (y1 - y0) / d))
    vecs.sort(key=lambda v: (round(v[1], 1), v[0]), reverse=True)
    return vecs[0]


def tls_coord(tls) -> tuple[float, float]:
    xs, ys = [], []
    for in_lane, _, _ in tls.getConnections():
        x, y = in_lane.getShape()[-1]
        xs.append(x); ys.append(y)
    return sum(xs) / len(xs), sum(ys) / len(ys)


def write_cfg(d: Path, net_name: str) -> None:
    (d / "sim.sumocfg").write_text(f"""<configuration>
    <input>
        <net-file value="{net_name}"/>
        <route-files value="routes.rou.xml"/>
        <additional-files value="tls.add.xml"/>
    </input>
    <time>
        <begin value="0"/>
        <end value="{END}"/>
        <step-length value="1"/>
    </time>
    <processing>
        <time-to-teleport value="300"/>
    </processing>
    <report>
        <no-step-log value="true"/>
        <no-warnings value="true"/>
    </report>
</configuration>
""")


def road_labels(net, is_major) -> list[dict]:
    """One label per street name, at the middle of its longest edge."""
    best = {}
    for e in net.getEdges():
        name = e.getName()
        if not name or e.getID().startswith(":"):
            continue
        if name not in best or e.getLength() > best[name].getLength():
            best[name] = e
    out = []
    for name, e in best.items():
        shape = e.getShape()
        (x0, y0), (x1, y1) = shape[0], shape[-1]
        out.append({"text": short_name(name), "x": round((x0 + x1) / 2, 1), "y": round((y0 + y1) / 2, 1),
                    "angle": round(math.degrees(math.atan2(y1 - y0, x1 - x0)), 1), "major": bool(is_major(e))})
    return out


def short_name(name: str) -> str:
    for a, b in (("Avenue", "Ave"), ("Street", "St"), ("West ", "W "), ("East ", "E ")):
        name = name.replace(a, b)
    return name


def export_web(net, sid: str, meta: dict, buildings: list | None = None, labels: list | None = None) -> None:
    lanes = []
    for e in net.getEdges():
        for lane in e.getLanes():
            lanes.append({"id": lane.getID(), "shape": [[round(x, 1), round(y, 1)] for x, y in lane.getShape()],
                          "w": round(lane.getWidth(), 2)})
    junctions = [{"id": n.getID(), "shape": [[round(x, 1), round(y, 1)] for x, y in n.getShape()]}
                 for n in net.getNodes() if len(n.getShape()) >= 3]
    tls = [{"id": t.getID(), "x": round(tls_coord(t)[0], 1), "y": round(tls_coord(t)[1], 1)}
           for t in net.getTrafficLights()]
    xs = [p[0] for l in lanes for p in l["shape"]]
    ys = [p[1] for l in lanes for p in l["shape"]]
    data = {"bounds": [min(xs), min(ys), max(xs), max(ys)], "lanes": lanes, "tls": tls, "junctions": junctions,
            "buildings": buildings or [], "labels": labels or [], "meta": meta}
    WEB.mkdir(parents=True, exist_ok=True)
    (WEB / f"{sid}.json").write_text(json.dumps(data, separators=(",", ":")))


def flow(fid, vtype, begin, end, vph, frm, to) -> str:
    return (f'  <flow id="{fid}" type="{vtype}" begin="{begin}" end="{end}" probability="{min(1, vph / 3600):.4f}" '
            f'from="{frm}" to="{to}" departLane="best" departSpeed="max"/>')


VTYPES = [
    '  <vType id="car" vClass="passenger" color="0.6,0.6,0.6"/>',
    '  <vType id="bus" vClass="bus" length="12" color="0.2,0.4,0.9"/>',
    '  <vType id="ambulance" vClass="emergency" speedFactor="1.3" color="1,0,0"/>',
    '  <vType id="crash" vClass="passenger" color="1,0.5,0"/>',
]


def write_routes(d: Path, routes: list[str], flows: list[tuple[int, str]]) -> None:
    lines = ["<routes>"] + VTYPES + routes + [f for _, f in sorted(flows, key=lambda x: x[0])] + ["</routes>"]
    (d / "routes.rou.xml").write_text("\n".join(lines) + "\n")


def node_near(net, a: str, b: str):
    """Signalized node where streets whose names contain a and b meet."""
    for n in net.getNodes():
        names = {e.getName() for e in n.getIncoming() + n.getOutgoing()}
        if any(a in x for x in names) and any(b in x for x in names):
            return n
    raise LookupError(f"no node at {a} / {b}")


# ------------------------------------------------------------------ 3x3 grid (the original demo city)

def build_grid() -> None:
    d = HERE / "grid"
    net_path = d / "grid.net.xml"
    subprocess.run(["netgenerate", "--grid", "--grid.number=3", "--grid.length=200", "--grid.attach-length=200",
                    "--default.lanenumber=2", "-j", "traffic_light", "-o", str(net_path)],
                   check=True, capture_output=True)
    net = sumolib.net.readNet(str(net_path), withPrograms=True)
    by_node = {}
    for n in net.getNodes():
        if len(n.getOutgoing()) == 1 and len(n.getIncoming()) == 1:
            by_node[n.getID()] = (n.getOutgoing()[0], n.getIncoming()[0])
    sources = {k: v[0] for k, v in by_node.items()}
    sinks = {k: v[1] for k, v in by_node.items()}
    opposite = lambda f: {"left": "right", "right": "left", "top": "bottom", "bottom": "top"}[f.rstrip("0123456789")] + f[-1]
    def turns(f):
        side, idx = f.rstrip("0123456789"), f[-1]
        return [c + idx for c in (("top", "bottom") if side in ("left", "right") else ("left", "right"))]

    periods = [(0, 600, 250, 150), (600, 1800, 750, 250), (1800, END, 250, 150)]
    flows = []
    for p, (b, e, main, cross) in enumerate(periods):
        for fid in sorted(sources):
            rate = main if fid.startswith(("left", "right")) else cross
            for to, vph in [(opposite(fid), rate * 0.8)] + [(t, rate * 0.1) for t in turns(fid)]:
                flows.append((b, flow(f"p{p}_{fid}_{to}", "car", b, e, vph, sources[fid].getID(), sinks[to].getID())))
    flows.append((0, f'  <flow id="bus" type="bus" begin="0" end="{END}" period="120" from="{sources["left1"].getID()}" '
                     f'to="{sinks["right1"].getID()}" departLane="best" departSpeed="max"/>'))
    amb, _ = net.getShortestPath(sources["bottom0"], sinks["right2"])
    routes = [f'  <route id="amb_route" edges="{" ".join(e.getID() for e in amb)}"/>']
    write_routes(d, routes, flows)
    is_major = lambda e: abs(e.getToNode().getCoord()[0] - e.getFromNode().getCoord()[0]) > 1
    stats = write_tls_programs(net, d / "tls.add.xml", is_major)
    write_cfg(d, net_path.name)

    meta = {
        "id": "grid", "title": "Demo grid", "subtitle": "3×3 downtown grid · 9 signals",
        "cfg": "scenario/grid/sim.sumocfg", "rush": list(RUSH), "end": END, "rotate_deg": 0,
        "major_label": "east–west", "expected_tls": 9,
        "ambulance": {"route": "amb_route", "label": "Ambulance across downtown"},
        "surge": {"label": "Stadium lets out", "from": [sources["bottom0"].getID(), sources["left0"].getID()],
                  "to": [sinks[k].getID() for k in ("right1", "right2", "top1", "top2")], "n": 120, "over_s": 240},
        "crash": {"label": "Crash on the main avenue", "edge": "B1C1", "lanes": [0, 1], "pos": 120, "duration": 300},
        "bus": "Crosstown bus every 2 min",
        "landmarks": [],
    }
    (d / "meta.json").write_text(json.dumps(meta, indent=2))
    export_web(net, "grid", meta, labels=[])
    print(f"grid: {len(net.getTrafficLights())} lights ({stats['greenwave_lights']} with green-wave programs)")


# ------------------------------------------------------------------ Midtown Manhattan from OpenStreetMap

MIDTOWN_CORNERS = [("6th Avenue", "47th Street"), ("6th Avenue", "55th Street"),
                   ("3rd Avenue", "55th Street"), ("3rd Avenue", "47th Street")]
OSM_TYPES = ",".join(f"highway.{t}" for t in
                     ("primary", "secondary", "tertiary", "residential", "unclassified",
                      "primary_link", "secondary_link", "tertiary_link"))


def build_midtown() -> None:
    d = HERE / "midtown"
    osm, raw, net_path = d / "midtown.osm.xml", d / "raw.net.xml", d / "midtown.net.xml"
    subprocess.run(["netconvert", "--osm-files", str(osm), "-o", str(raw), "--keep-edges.by-type", OSM_TYPES,
                    "--keep-edges.by-vclass", "passenger", "--geometry.remove", "--roundabouts.guess",
                    "--ramps.guess", "--junctions.join", "--tls.guess-signals", "--tls.discard-simple",
                    "--tls.join", "--tls.default-type", "static", "--output.street-names", "--no-turnarounds",
                    "--edges.join", "--osm.sidewalks", "false", "--crossings.guess", "false", "--no-warnings"],
                   check=True, capture_output=True)

    # crop to the rectangle between the four corner intersections (plus one approach block outside)
    rawnet = sumolib.net.readNet(str(raw))
    poly = [node_near(rawnet, a, b).getCoord() for a, b in MIDTOWN_CORNERS]
    cx, cy = sum(p[0] for p in poly) / 4, sum(p[1] for p in poly) / 4
    poly = [(cx + (x - cx) * 1.04, cy + (y - cy) * 1.04) for x, y in poly]
    keep = [e.getID() for e in rawnet.getEdges()
            if _inside(e.getFromNode().getCoord(), poly) or _inside(e.getToNode().getCoord(), poly)]
    keep_file = d / "keep.txt"
    keep_file.write_text("\n".join(keep))
    speed_file = d / "speed.edg.xml"
    speed_file.write_text("<edges>\n" + "\n".join(f'  <edge id="{e}" speed="{NYC_SPEED}"/>' for e in keep) + "\n</edges>\n")
    subprocess.run(["netconvert", "-s", str(raw), "--keep-edges.input-file", str(keep_file), "-e", str(speed_file),
                    "-o", str(net_path), "--output.street-names", "--no-turnarounds", "--no-warnings"],
                   check=True, capture_output=True)
    for f in (raw, keep_file, speed_file):
        f.unlink()

    net = sumolib.net.readNet(str(net_path), withPrograms=True)
    is_major = lambda e: "Avenue" in e.getName()
    sources, sinks = fringe(net)
    rng = random.Random(7)

    # demand: per-lane rates; avenues carry the rush, cross streets stay lighter
    rates = {  # (begin, end): (avenue veh/h/lane, street veh/h/lane)
        (0, RUSH[0]): (90, 70), (RUSH[0], RUSH[1]): (230, 120), (RUSH[1], END): (90, 70)}
    flows = []
    sink_ix = {k.getID(): i for i, k in enumerate(sinks)}
    for p, ((b, e), (av, st)) in enumerate(rates.items()):
        for si, s in enumerate(sources):
            per_lane = av if is_major(s) else st
            vph = per_lane * min(s.getLaneNumber(), 4)
            straight = [k for k in sinks if k.getName() == s.getName()]
            straight = max(straight, key=lambda k: _dist(s, k)) if straight else None
            others = [k for k in sinks if k is not straight and _dist(s, k) > 150]
            turns = rng.sample(others, min(3, len(others)))
            dests = ([(straight, 0.7)] if straight else []) + [(k, (0.3 if straight else 1.0) / len(turns)) for k in turns]
            for k, share in dests:
                flows.append((b, flow(f"m{p}_{si}_{sink_ix[k.getID()]}", "car", b, e, vph * share, s.getID(), k.getID())))

    def on(name, edges, pick):
        cand = [e for e in edges if e.getName() == name]
        return pick(cand) if cand else None
    # buses: southbound on 5th Ave, northbound on Madison
    for name in ("5th Avenue", "Madison Avenue"):
        src = on(name, sources, lambda c: c[0])
        dst = on(name, sinks, lambda c: max(c, key=lambda k: _dist(src, k))) if src else None
        if src and dst:
            flows.append((0, f'  <flow id="bus_{name.split()[0]}" type="bus" begin="30" end="{END}" period="150" '
                             f'from="{src.getID()}" to="{dst.getID()}" departLane="best" departSpeed="max"/>'))

    # ambulance: north on 3rd Ave, west on 55th St, toward Mount Sinai West
    amb_from = on("3rd Avenue", sources, lambda c: min(c, key=lambda e: e.getFromNode().getCoord()[1]))
    amb_to = on("West 55th Street", sinks, lambda c: c[0]) or on("East 55th Street", sinks, lambda c: c[0])
    amb, _ = net.getShortestPath(amb_from, amb_to)
    routes = [f'  <route id="amb_route" edges="{" ".join(e.getID() for e in amb)}"/>']
    write_routes(d, routes, flows)
    stats = write_tls_programs(net, d / "tls.add.xml", is_major)
    write_cfg(d, net_path.name)

    # events
    radio_city = node_near(net, "6th Avenue", "50th Street")
    surge_from = sorted({e.getID() for e in radio_city.getOutgoing() + radio_city.getIncoming()
                         if e.getID() in {x.getID() for x in net.getEdges()}})
    far_sinks = sorted(sinks, key=lambda k: -_dist_xy(radio_city.getCoord(), k.getToNode().getCoord()))[:6]
    st_pats = node_near(net, "5th Avenue", "51st Street")
    crash_edge = next(e for e in st_pats.getOutgoing() if e.getName() == "5th Avenue")

    landmarks = [("Radio City", "6th Avenue", "50th Street"), ("St. Patrick's", "5th Avenue", "50th Street"),
                 ("Rockefeller Ctr", "6th Avenue", "49th Street"), ("MoMA", "6th Avenue", "53rd Street"),
                 ("Grand Central ↓", "Park Avenue", "47th Street")]
    lm = []
    for text, a, b in landmarks:
        try:
            x, y = node_near(net, a, b).getCoord()
            lm.append({"text": text, "x": round(x, 1), "y": round(y, 1)})
        except LookupError:
            pass

    rot = _avenue_rotation(net)
    meta = {
        "id": "midtown", "title": "Midtown Manhattan", "subtitle": "6th–3rd Ave · 47th–55th St · 54 signals",
        "cfg": "scenario/midtown/sim.sumocfg", "rush": list(RUSH), "end": END, "rotate_deg": rot,
        "major_label": "avenues", "expected_tls": 54,
        "ambulance": {"route": "amb_route", "label": "Ambulance → Mount Sinai West"},
        "surge": {"label": "Radio City show lets out", "from": surge_from, "to": [k.getID() for k in far_sinks],
                  "n": 160, "over_s": 240},
        "crash": {"label": "Crash on 5th Ave at St. Patrick's", "edge": crash_edge.getID(),
                  "lanes": [0, 1], "pos": round(crash_edge.getLength() * 0.6, 1), "duration": 300},
        "bus": "5th Ave & Madison buses every 2.5 min",
        "landmarks": lm,
        "attribution": "Map data © OpenStreetMap contributors (ODbL)",
    }
    (d / "meta.json").write_text(json.dumps(meta, indent=2))
    export_web(net, "midtown", meta, buildings=_buildings(osm, net_path, net), labels=road_labels(net, is_major))
    print(f"midtown: {len(net.getTrafficLights())} lights ({stats['greenwave_lights']} green-wave), "
          f"{len(sources)} sources, {len(sinks)} sinks, ambulance {len(amb)} edges, rotate {rot}°")


def _avenue_rotation(net) -> float:
    """Degrees to rotate the map so 6th Ave runs straight up the screen."""
    (x0, y0), (x1, y1) = node_near(net, "6th Avenue", "47th Street").getCoord(), node_near(net, "6th Avenue", "55th Street").getCoord()
    return round(math.degrees(math.atan2(x1 - x0, y1 - y0)), 2)


def _buildings(osm: Path, net_path: Path, net) -> list:
    poly_path = net_path.parent / "buildings.poly.xml"
    typemap = Path(sumo.SUMO_HOME) / "data" / "typemap" / "osmPolyconvert.typ.xml"
    subprocess.run(["polyconvert", "--osm-files", str(osm), "--net-file", str(net_path), "--type-file", str(typemap),
                    "-o", str(poly_path), "--no-warnings"], check=True, capture_output=True)
    xmin, ymin, xmax, ymax = net.getBoundary()
    pad = 60
    out = []
    for p in ET.parse(poly_path).getroot().iter("poly"):
        if not p.get("type", "").startswith("building"):
            continue
        pts = [tuple(map(float, xy.split(","))) for xy in p.get("shape").split()]
        if not all(xmin - pad <= x <= xmax + pad and ymin - pad <= y <= ymax + pad for x, y in pts):
            continue
        out.append([[round(x), round(y)] for x, y in pts])
    poly_path.unlink()
    return out


def _inside(pt, poly) -> bool:
    x, y = pt
    c = False
    for i in range(len(poly)):
        (x1, y1), (x2, y2) = poly[i], poly[i - 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


def _dist(a, b) -> float:
    return _dist_xy(a.getFromNode().getCoord(), b.getToNode().getCoord())


def _dist_xy(p, q) -> float:
    return math.hypot(p[0] - q[0], p[1] - q[1])


SCENARIOS = {"grid": build_grid, "midtown": build_midtown}

if __name__ == "__main__":
    for sid in (sys.argv[1:] or SCENARIOS):
        SCENARIOS[sid]()
