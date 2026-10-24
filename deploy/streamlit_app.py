"""Hosted replay of the CivicSignal dashboard, for Streamlit Community Cloud.

Streamlit can't run the live sim: the dashboard steers it over server.py's websocket. This page embeds
the same dashboard in replay mode instead (built by build_site.py), playing recordings/demo.jsonl, with the
3-seed benchmark below.

    pip install -r deploy/requirements.txt
    streamlit run deploy/streamlit_app.py
"""
from __future__ import annotations

import streamlit as st

from build_site import ROOT, dashboard_html   # streamlit puts this script's folder on sys.path

REPO_URL = "https://github.com/shivansh980/Smart-traffic-manager"
HEIGHT = 900       # the dashboard is laid out for a 1440 x 900 screen


def benchmark(name: str) -> str:
    text = (ROOT / "results" / f"compare_{name}.md").read_text()
    return text.split("\n", 1)[1] if text.startswith("# ") else text   # the tab label replaces the title


st.set_page_config(page_title="CivicSignal: Smart traffic manager", page_icon="🚦", layout="wide")
st.html("<style>[data-testid='stMainBlockContainer'] { padding: 3.5rem 1.5rem 3rem; max-width: none; }</style>")

st.title("CivicSignal: traffic lights the city can steer")
st.markdown(
    "Same cars, same seed, two cities: **fixed-time signals** (left) against **CivicSignal** (right), a weighted "
    "max-pressure controller that reads live queues. This is a recorded run of the 3×3 demo grid: rush hour hits "
    "at 10:00, an ambulance is dispatched at 15:51, then a crowd surge and a crash. The live version, with the "
    f"ambulance button, policy sliders and copilot, runs on a laptop: see the [README]({REPO_URL}#run-it)."
)
st.iframe(st.cache_data(dashboard_html)(), height=HEIGHT)

st.header("Benchmark")
st.caption("Every strategy on both maps, 3 seeds × 2400 s, mean ± std, every seed reported. "
           "Reproduce with `python compare.py --scenario all --seeds 1 2 3`.")
for tab, name in zip(st.tabs(["Midtown Manhattan (54 signals)", "Demo grid (9 signals)"]), ("midtown", "grid")):
    with tab:
        st.markdown(benchmark(name))
