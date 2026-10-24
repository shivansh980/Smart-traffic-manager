"""Build the 3x3 grid scenario: net, routes, sumocfg, and web/net.json.

    python scenario/build.py
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import sumolib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
NET = HERE / "grid.net.xml"
ROUTES = HERE / "routes.rou.xml"
CFG = HERE / "sim.sumocfg"
NET_JSON = ROOT / "web" / "net.json"

END = 2400
# (begin, end, main-axis veh/h per entry, cross-street veh/h per entry)
# Main axis is east-west. Rush hour is ~3x the cross street, which is where adaptive control pays off.
PERIODS = [
    (0, 600, 250, 150),
    (600, 1800, 750, 250),
    (1800, END, 250, 150),
]
TURN_SHARE = 0.2   # share of each entry's demand that turns onto the cross axis
BUS_PERIOD = 120


def run_netgenerate() -> None:
    subprocess.run(
        ["netgenerate", "--grid", "--grid.number=3", "--grid.length=200", "--grid.attach-length=200",
         "--default.lanenumber=2", "-j", "traffic_light", "-o", str(NET)],
        check=True, capture_output=True,
    )


def fringe_edges(net) -> tuple[dict[str, object], dict[str, object]]:
    """Fringe nodes are dead ends: one edge in, one edge out. Keyed by fringe node id."""
    sources, sinks = {}, {}
    for node in net.getNodes():
        if len(node.getOutgoing()) == 1 and len(node.getIncoming()) == 1:
            sources[node.getID()] = node.getOutgoing()[0]
            sinks[node.getID()] = node.getIncoming()[0]
    return sources, sinks


def opposite(fringe_id: str) -> str:
    side, idx = fringe_id.rstrip("0123456789"), fringe_id[-1]
    return {"left": "right", "right": "left", "top": "bottom", "bottom": "top"}[side] + idx


def turn_targets(fringe_id: str) -> list[str]:
    """The two cross-axis exits a turning vehicle from this entry heads for."""
    side, idx = fringe_id.rstrip("0123456789"), fringe_id[-1]
    cross = ("top", "bottom") if side in ("left", "right") else ("left", "right")
    return [c + idx for c in cross]


def write_routes(net) -> str:
    sources, sinks = fringe_edges(net)
    assert len(sources) == 12, f"expected 12 fringe entries, got {len(sources)}"

    lines = [
        "<routes>",
        '  <vType id="car" vClass="passenger" color="0.6,0.6,0.6"/>',
        '  <vType id="bus" vClass="bus" length="12" color="0.2,0.4,0.9"/>',
        '  <vType id="ambulance" vClass="emergency" speedFactor="1.3" color="1,0,0"/>',
    ]

    amb_path, _ = net.getShortestPath(sources["bottom0"], sinks["right2"])
    amb_edges = " ".join(e.getID() for e in amb_path)
    lines.append(f'  <route id="amb_route" edges="{amb_edges}"/>')

    flows = []
    for p, (begin, end, main, cross) in enumerate(PERIODS):
        for fid in sorted(sources):
            rate = main if fid.startswith(("left", "right")) else cross
            dests = [(opposite(fid), rate * (1 - TURN_SHARE))]
            dests += [(t, rate * TURN_SHARE / 2) for t in turn_targets(fid)]
            for to, vph in dests:
                flows.append((begin, f'  <flow id="p{p}_{fid}_{to}" type="car" begin="{begin}" end="{end}" '
                                     f'probability="{vph / 3600:.4f}" from="{sources[fid].getID()}" '
                                     f'to="{sinks[to].getID()}" departLane="best" departSpeed="max"/>'))
    flows.append((0, f'  <flow id="bus" type="bus" begin="0" end="{END}" period="{BUS_PERIOD}" '
                     f'from="{sources["left1"].getID()}" to="{sinks["right1"].getID()}" '
                     f'departLane="best" departSpeed="max"/>'))
    # SUMO wants flows sorted by begin time
    lines += [f for _, f in sorted(flows, key=lambda x: x[0])]
    lines.append("</routes>")
    ROUTES.write_text("\n".join(lines) + "\n")
    return amb_edges


def write_cfg() -> None:
    CFG.write_text(f"""<configuration>
    <input>
        <net-file value="{NET.name}"/>
        <route-files value="{ROUTES.name}"/>
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


def export_net_json(net) -> None:
    lanes = []
    for edge in net.getEdges():
        for lane in edge.getLanes():
            if lane.getID().startswith(":"):
                continue
            lanes.append({"id": lane.getID(),
                          "shape": [[round(x, 2), round(y, 2)] for x, y in lane.getShape()],
                          "w": round(lane.getWidth(), 2)})
    tls = [{"id": n.getID(), "x": round(n.getCoord()[0], 2), "y": round(n.getCoord()[1], 2)}
           for n in net.getNodes() if n.getType() == "traffic_light" and len(n.getOutgoing()) > 1]
    xmin, ymin, xmax, ymax = net.getBoundary()
    NET_JSON.parent.mkdir(exist_ok=True)
    NET_JSON.write_text(json.dumps({"bounds": [xmin, ymin, xmax, ymax], "lanes": lanes, "tls": tls}))


def main() -> None:
    run_netgenerate()
    net = sumolib.net.readNet(str(NET))
    amb = write_routes(net)
    write_cfg()
    export_net_json(net)
    print(f"wrote {NET.name}, {ROUTES.name}, {CFG.name}, web/net.json")
    print(f"ambulance route: {amb}")


if __name__ == "__main__":
    main()
