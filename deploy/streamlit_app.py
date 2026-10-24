"""Hosted replay of the CivicSignal dashboard, for Streamlit Community Cloud.

Streamlit can't run the live sim: the dashboard steers it over server.py's websocket. This page embeds
the same dashboard in replay mode instead, playing recordings/demo.jsonl, with the 3-seed benchmark below.
Everything is inlined into one HTML document. The data files ship gzipped, and a fetch shim inflates
them in the browser when app.js asks for them.

    pip install -r deploy/requirements.txt
    streamlit run deploy/streamlit_app.py
"""
from __future__ import annotations

import base64
import gzip
import json
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
REPLAY = ROOT / "recordings" / "demo.jsonl"
REPO_URL = "https://github.com/shivansh980/Smart-traffic-manager"
START_T = 540      # just before rush hour (600 s); the totals still count from t = 0
HEIGHT = 900       # the dashboard is laid out for a 1440 x 900 screen

# Pop-outs open /?view=..., which only server.py serves, and there's no server connection to show.
EXTRA_CSS = ".pop, #conn { display: none !important; }"

FETCH_SHIM = """<script>
window.CIVIC_PARAMS = %(params)s;
(() => {
  const packed = %(packed)s;
  const netFetch = window.fetch.bind(window);
  window.fetch = async (url, opts) => {
    if (!Object.hasOwn(packed, url)) return netFetch(url, opts);
    const bytes = Uint8Array.from(atob(packed[url]), (c) => c.charCodeAt(0));
    return new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip')));
  };
})();
</script>"""


def _packed(path: Path) -> str:
    return base64.b64encode(gzip.compress(path.read_bytes(), 9)).decode()


def _inline(html: str, tag: str, content: str) -> str:
    assert tag in html, f"web/index.html no longer contains {tag!r}"
    return html.replace(tag, content)


@st.cache_data
def dashboard_html() -> str:
    packed = {"demo.jsonl": _packed(REPLAY)}
    packed |= {f"scenarios/{p.name}": _packed(p) for p in sorted((WEB / "scenarios").glob("*.json"))}
    shim = FETCH_SHIM % {"params": json.dumps(f"replay=demo.jsonl&autoplay&t={START_T}"),
                         "packed": json.dumps(packed)}
    html = (WEB / "index.html").read_text()
    html = _inline(html, '<link rel="stylesheet" href="style.css">',
                   f"<style>{(WEB / 'style.css').read_text()}\n{EXTRA_CSS}</style>")
    html = _inline(html, '<script src="vendor/chart.umd.min.js"></script>',
                   f"<script>{(WEB / 'vendor' / 'chart.umd.min.js').read_text()}</script>")
    html = _inline(html, '<script src="app.js"></script>',
                   f"{shim}\n<script>{(WEB / 'app.js').read_text()}</script>")
    return html


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
st.iframe(dashboard_html(), height=HEIGHT)

st.header("Benchmark")
st.caption("Every strategy on both maps, 3 seeds × 2400 s, mean ± std, every seed reported. "
           "Reproduce with `python compare.py --scenario all --seeds 1 2 3`.")
for tab, name in zip(st.tabs(["Midtown Manhattan (54 signals)", "Demo grid (9 signals)"]), ("midtown", "grid")):
    with tab:
        st.markdown(benchmark(name))
