"""Builds the hosted replay of the CivicSignal dashboard: one self-contained HTML file, no server needed.

The live dashboard steers the sim over server.py's websocket, which a static host can't run. This page plays
recordings/demo.jsonl in replay mode instead, so it works from disk or on any static host (GitHub Pages,
Netlify), and deploy/streamlit_app.py embeds the same page. Everything is inlined into one document. The data
files ship gzipped, and a fetch shim inflates them in the browser when app.js asks for them.

    python deploy/build_site.py              # writes docs/index.html (GitHub Pages: main branch, /docs)
    python deploy/build_site.py --out x.html
"""
from __future__ import annotations

import argparse
import base64
import gzip
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
REPLAY = ROOT / "recordings" / "demo.jsonl"
START_T = 540      # just before rush hour (600 s); the totals still count from t = 0

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
    return base64.b64encode(gzip.compress(path.read_bytes(), 9, mtime=0)).decode()   # mtime=0: same input, same bytes


def _inline(html: str, tag: str, content: str) -> str:
    assert tag in html, f"web/index.html no longer contains {tag!r}"
    return html.replace(tag, content)


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


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "index.html")
    out = ap.parse_args().out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(dashboard_html())
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB)")
