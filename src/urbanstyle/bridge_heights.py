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
    for aid, a in axes.items():
        h = H.get(aid)
        if isinstance(h, list):
            a["vertical"] = _vertical(h, d["curve_m"], "heights file: the points given")
        elif isinstance(h, dict) and h.get("from"):
            later.append((a, h))
        else:
            a["vertical"] = _vertical(_rule(a, d["grade"], d["max_m"]), d["curve_m"],
                                      f"heights file default: {d['grade'] * 100:.0f}% up from each end on the ground, at most {d['max_m']} m")
    for a, h in later:          # a ramp: from the other axis's height where they meet, down at grade to the ground
        o = axes.get(h["from"])
        if o is None:
            continue
        L = a["length_m"]
        # (the end where they meet: the one whose node the other axis has)
        o_nodes = {e.get("node"): e["s"] for e in o.get("ends", []) if e.get("node")}
        e_meet = next((k for k, e in enumerate(a["ends"]) if e.get("node") in o_nodes), 0)
        z0 = height(o["vertical"], o_nodes.get(a["ends"][e_meet].get("node"), 0.0))
        run = z0 / d["grade"] if h.get("to_ground", True) else L
        pts = [[0, z0], [min(run, L), max(z0 - d["grade"] * L, 0.0) if run >= L else 0.0]] + ([[L, 0.0]] if run < L else [])
        if e_meet == 1:
            pts = [[L - s, z] for s, z in pts]
        a["vertical"] = _vertical(pts, d["curve_m"], f"heights file: from {h['from']}'s height where they meet, {d['grade'] * 100:.0f}% down to the ground")
    return P


def write(profile, heights, out):
    """The profile at `profile` with the heights of `heights` (its entry for the profile's bridge name), to `out`. Returns the axes set."""
    P = json.load(open(profile))
    H = json.load(open(heights)).get(P["name"], {})
    apply(P, H)
    with open(out, "w") as f:
        json.dump(P, f, indent=1)
    return len(P["axes"])
