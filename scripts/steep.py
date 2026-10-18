"""Count the steep faces (a wall over 1 m that is not a guard) in a page's bridge3d.json: python steep.py viz/cut-NAME.bridge3d.json"""
import json, sys, math
from collections import Counter
models = json.load(open(sys.argv[1])); models = models if isinstance(models, list) else [models]
def steep(v, f):
    p = [v[i] for i in f]; zs = [q[2] for q in p]; dz = max(zs) - min(zs)
    h = max(math.dist(p[a][:2], p[b][:2]) for a, b in ((0, 1), (1, 2), (0, 2)))
    return dz > 1.0 and dz > h
cc, where, total = Counter(), Counter(), 0
for m in models:
    lon0, lat0 = m["origin"]; k = 111320 * math.cos(math.radians(lat0))
    for s in m.get("surf", []):
        if str(s.get("key", "")).startswith(("barrier", "railing")): continue
        for f in s["f"]:
            if steep(s["v"], f):
                total += 1; cc[s["key"]] += 1; p = s["v"][f[0]]; where[(round(lon0 + p[0] / k, 5), round(lat0 + p[1] / 111320, 5))] += 1
print("steep non-guard faces:", total); print("by kind:", cc.most_common(10)); print("where:", where.most_common(8))
