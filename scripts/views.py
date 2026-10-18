"""Headless 3D views of a page: python views.py URL TAG lon:lat:zoom:pitch:bearing ...  -> viz/review/TAG-<k>.png"""
import sys
from playwright.sync_api import sync_playwright
url, tag = sys.argv[1], sys.argv[2]
views = [tuple(float(v) for v in s.split(":")) for s in sys.argv[3:]]
with sync_playwright() as p:
    br = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--ignore-gpu-blocklist"])
    pg = br.new_page(viewport={"width": 1200, "height": 800})
    pg.goto(url, wait_until="domcontentloaded", timeout=120000)
    pg.wait_for_function("() => !document.getElementById('xpveil')", timeout=180000)
    pg.wait_for_timeout(3000)
    pg.evaluate("() => { const f = document.getElementById('xpfold'); if (f && !document.body.classList.contains('xp-off')) f.click() }")
    pg.evaluate("() => { const t = document.getElementById('lowbld'); if (t && !t.checked) t.click() }")
    for k, (x, y, z, pt, b) in enumerate(views):
        pg.evaluate(f"() => window.map.jumpTo({{center: [{x}, {y}], zoom: {z}, pitch: {pt}, bearing: {b}}})")
        pg.wait_for_timeout(18000)
        pg.screenshot(path=f"viz/review/{tag}-{k}.png"); print("shot", k, flush=True)
    br.close()
