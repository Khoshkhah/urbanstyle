"""Bridge heights without LiDAR (docs/design/bridge-heights.md): `urbanstyle bridge-heights PROFILE HEIGHTS OUT` gives each axis of a
bridge profile a vertical profile from a small heights file: points [s, height] per axis, a ramp from another axis down to the ground,
or the default rule (up from each end on the ground at `grade` to `max_m`). Only each axis's `vertical` changes."""
import json

DEFAULT = {"grade": 0.05, "max_m": 27.0, "curve_m": 60.0}


def _vertical(points, curve_m, rule):
    """A vertical profile from points [s, height]: each inside point rounded by a vertical curve of curve_m (at most 0.9 of the shorter
    grade beside it)."""
    pts = [[round(float(s), 2), round(float(z), 2)] for s, z in sorted(points)]
    curves = [0.0] + [round(min(curve_m, 0.9 * min(pts[i][0] - pts[i - 1][0], pts[i + 1][0] - pts[i][0])), 1)
                      for i in range(1, len(pts) - 1)] + ([0.0] if len(pts) > 1 else [])
    return {"points": pts, "curves": curves, "source": "urbanstyle", "method": "chosen", "rule": rule}


def _rule(a, grade, max_m):
    """The default rule: up from each end on the ground at grade to max_m, max_m between; no end on the ground: max_m."""
    L = a["length_m"] if "length_m" in a else a["line"]["value"] and _length(a["line"]["value"])
    g0, g1 = (bool(e.get("ground")) for e in (a["ends"] + [{}, {}])[:2])
    rise = max_m / grade
    if g0 and g1:
        if 2 * rise >= L:           # (too short to reach max_m: a crest in the middle)
            return [[0, 0], [L / 2, grade * L / 2], [L, 0]]
        return [[0, 0], [rise, max_m], [L - rise, max_m], [L, 0]]
    if g0:
        return [[0, 0], [min(rise, L), min(max_m, grade * L)]] + ([[L, max_m]] if rise < L else [])
    if g1:
        return ([[0, max_m]] if rise < L else []) + [[max(L - rise, 0), min(max_m, grade * L)], [L, 0]]
    return [[0, max_m], [L, max_m]]


def _length(pts):
    import math
    return sum(math.dist(p[:2], q[:2]) for p, q in zip(pts, pts[1:]))


def apply(P, H):
    """Profile P with the vertical profiles that heights entry H (one bridge's) gives. Returns P."""
    from .bridge_profile import height
    d = {**DEFAULT, **(H.get("default") or {})}
    axes = {a["id"]: a for a in P["axes"]}
    for a in P["axes"]:
        a.setdefault("length_m", round(_length(a["line"]["value"]), 2))
    later = []
    known = P.setdefault("heights", {})
    for k, h in H.items():                        # (one height at a junction or an end: the key is its OSM node, "n<id>")
        if k.startswith("n") and k[1:].isdigit() and isinstance(h, (int, float)):
            known[k] = {"deck_m": float(h), "source": "heights file", "method": "chosen"}
    for aid, a in axes.items():
        h = H.get(aid)
        if isinstance(h, (int, float)):               # (one number for an axis: its height at its middle)
            known[aid] = {"mid_m": float(h), "source": "heights file", "method": "chosen"}
            continue
        if isinstance(h, list):
            a["vertical"] = _vertical(h, d["curve_m"], "heights file: the points given")
            known[aid] = {"points": a["vertical"]["points"], "curves": a["vertical"].get("curves"), "source": "heights file", "method": "chosen"}
        elif isinstance(h, dict) and h.get("from"):
            later.append((a, h))
        else:
            a["vertical"] = _vertical(_rule(a, d["grade"], d["max_m"]), d["curve_m"],
                                      f"heights file default: {d['grade'] * 100:.0f}% up from each end on the ground, at most {d['max_m']} m")
    # an axis with both ends in the air that the file does not name: straight between the heights of the axes it meets there, where those
    # are given (a4, a9, a10 between a1 and the ramps; at max_m they met a1 2 m off)
    given = {aid for aid, h in H.items() if isinstance(h, list)}
    node_h = {}
    for aid in given:
        a = axes[aid]
        for e in a.get("ends", []):
            if e.get("node"):
                node_h[e["node"]] = height(a["vertical"], e["s"])
    for aid, a in axes.items():
        if aid in H or any(e.get("ground") for e in a.get("ends", [])):
            continue
        hs = [node_h.get(e.get("node")) for e in a["ends"][:2]]
        if len(hs) == 2 and None not in hs:
            a["vertical"] = _vertical([[0, hs[0]], [a["length_m"], hs[1]]], d["curve_m"], "heights file default: straight between the axes it meets")
        elif len(hs) == 2 and any(h_ is not None for h_ in hs):
            h_ = next(h_ for h_ in hs if h_ is not None)
            a["vertical"] = _vertical([[0, h_], [a["length_m"], h_]], d["curve_m"], "heights file default: level with the axis it meets")
        for k, e in enumerate(a["ends"][:2]):        # (its ends known now, for the ramps from it)
            if e.get("node") and e["node"] not in node_h:
                node_h[e["node"]] = height(a["vertical"], e["s"])
    for a, h in later:          # a ramp: from the other axis's height where they meet, down at grade to the ground
        o = axes.get(h["from"])
        if o is None:
            continue
        L = a["length_m"]
        # (the end where they meet: the one whose node the other axis has)
        o_nodes = {e.get("node"): e["s"] for e in o.get("ends", []) if e.get("node")}
        e_meet = next((k for k, e in enumerate(a["ends"]) if e.get("node") in o_nodes), 0)
        z0 = height(o["vertical"], o_nodes.get(a["ends"][e_meet].get("node"), 0.0))
        g = d["grade"]
        if h.get("to_ground", True) and z0 / g > L:
            g = z0 / L          # (a ramp too short for the grade: as steep as it must be to reach the ground at its end)
        run = z0 / g if h.get("to_ground", True) else L
        pts = [[0, z0], [min(run, L), max(z0 - g * L, 0.0) if run >= L else 0.0]] + ([[L, 0.0]] if run < L else [])
        if e_meet == 1:
            pts = [[L - s, z] for s, z in pts]
        a["vertical"] = _vertical(pts, d["curve_m"], f"heights file: from {h['from']}'s height where they meet, {g * 100:.1f}% down to the ground")
    return P


def from_vertical(P):
    """The profile's `heights` section from each axis whose vertical is measured (LiDAR): its fitted points and curves, a few per axis
    (Granville: 77 points on 12 axes from 350 stations). Axes with chosen heights get no entry: the rule fills them. Returns P."""
    H = P.setdefault("heights", {})
    for a in P["axes"]:
        v = a["vertical"]
        if "lidar" in str(v.get("source", "")).lower() or "measured" in str(v.get("method", "")).lower():
            H[a["id"]] = {"points": v["points"], "curves": v.get("curves"), "source": v.get("source"), "method": "measured"}
    return P


def write(profile, heights, out):
    """The profile at `profile` with the heights of `heights` (its entry for the profile's bridge name), to `out`. Returns the axes set."""
    P = json.load(open(profile))
    H = json.load(open(heights)).get(P["name"], {})
    apply(P, H)
    with open(out, "w") as f:
        json.dump(P, f, indent=1)
    return len(P["axes"])
