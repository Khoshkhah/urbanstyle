"""A bridge's structure under its deck, from its profile: the piers (two columns under each pier, with free space between them) and,
where corrections/bridges.json names one, the steel truss under a span with its concrete piers, legs and bents. The code of
bridge3d.model, moved here so the street model of the deck (deck3d) has the same structure (docs/notes/bridges-street-model.md).

    structure(P, axes, deck, frame, deck_m) -> (piers, truss), in the profile's metres:
        piers  [{"a": [x, y], "b": [x, y], "t": thickness, "h": height}]
        truss  [{"a": [x, y, z], "b": [x, y, z], "w": width, "n": normal (optional)}]
"""
from .bridge3d import (BENT_LEG_M, COLUMN_GAP_M, COLUMN_M, TRUSS_CROWN_M, TRUSS_IN_M, TRUSS_M, TRUSS_PANEL_M, TRUSS_PIER_M, _h)


def structure(P, axes, deck, frame, deck_m):
    import shapely
    from .corrections import bridge as bridge_corr_tr
    DECK_M = deck_m
    by_id = {a["id"]: (ln, a) for ln, a in axes}
    trusses_ = bridge_corr_tr(P["name"]).get("truss", [])
    piers = []
    for q in P["piers"]:
        # none where a steel truss stands: the truss and its own piers replace these rule-made ones (Kaveh, 2026-10-12)
        if any(q["axis"] == tr_.get("axis") and tr_["s0"] <= q["s"] <= tr_["s1"] for tr_ in trusses_):
            continue
        ln, a = by_id[q["axis"]]
        x, y, nx, ny = frame(ln, q["s"])
        # across its own road only (its bands at s), inside the deck
        sec = next((sc for sc in a["sections"] if sc["s0"] - 0.01 <= q["s"] <= sc["s1"] + 0.01), None)
        bs = sec["bands"] if sec else []
        lo = min((b["t"] - b["width"]["value"] / 2 for b in bs), default=-4.0) + 0.5
        hi = max((b["t"] + b["width"]["value"] / 2 for b in bs), default=4.0) - 0.5
        if hi - lo <= COLUMN_M:     # (a road narrower than a column: one column on its middle; a one-lane road had none, a2 of
            mid_ = (lo + hi) / 2    # Boulevard du Larvotto; Kaveh, 2026-10-14)
            lo, hi = mid_ - COLUMN_M / 2 - 0.01, mid_ + COLUMN_M / 2 + 0.01
        cut = shapely.LineString([(x + nx * lo, y + ny * lo), (x + nx * hi, y + ny * hi)]).intersection(deck.buffer(0.5))
        h = _h(a["vertical"], q["s"]) - DECK_M
        for seg in shapely.get_parts(cut):
            if seg.geom_type == "LineString" and seg.length > COLUMN_M:
                # two columns, one under each edge of the road, with free space between them (one under a road too narrow for two)
                ends = [0.0, seg.length] if seg.length >= 2 * COLUMN_M + COLUMN_GAP_M else [seg.length / 2]
                for d in ends:
                    d0 = min(max(d - COLUMN_M / 2, 0.0), seg.length - COLUMN_M)
                    (ax, ay), (bx, by) = seg.interpolate(d0).coords[0], seg.interpolate(d0 + COLUMN_M).coords[0]
                    piers.append({"a": [round(ax, 2), round(ay, 2)], "b": [round(bx, 2), round(by, 2)], "t": COLUMN_M, "h": round(h, 2)})
    # the steel truss under a span, corrections/bridges.json "truss": [{axis, s0, s1, panel, spring_z, crown_gap}] (Kaveh, 2026-10-12: "it
    # has some steel parts with a special pattern between its legs"; the pattern from the city's photos, 2011-07-21 Vancouver 06, the
    # heights from the profile): on each side, under the deck's edge, a top chord under the deck, a bottom chord arched from its springing
    # points to crown_gap under the deck mid-span, a vertical at each panel point and a diagonal in each panel, in a V pattern
    truss = []

    def planes_(ln, s_):
        """The axis's frame at s_ and the two truss planes' t, TRUSS_IN_M in from the deck's edges (None off the deck)."""
        x, y, nx, ny = frame(ln, s_)
        cut_ = shapely.LineString([(x - nx * 40, y - ny * 40), (x + nx * 40, y + ny * 40)]).intersection(deck)
        ts_ = [(q[0] - x) * nx + (q[1] - y) * ny for g_ in shapely.get_parts(cut_) if g_.geom_type == "LineString" for q in g_.coords]
        return (x, y, nx, ny, {1: max(ts_) - TRUSS_IN_M, -1: min(ts_) + TRUSS_IN_M}) if ts_ else None
    for tr_ in trusses_:
        if tr_.get("axis") not in by_id:
            continue
        ln, a = by_id[tr_["axis"]]
        # a concrete pier under each springing point ("piers": [s]): one block across the deck from the ground to the springing
        # height, wider than the two truss planes (Kaveh, 2026-10-12; photos 2011-07-21 Vancouver 06, the orthophoto's shores)
        for s_ in tr_.get("piers", []):
            f_ = planes_(ln, s_)
            if f_:
                x, y, nx, ny, t_ = f_
                lo_, hi_ = t_[-1] - TRUSS_PIER_M[1], t_[1] + TRUSS_PIER_M[1]
                piers.append({"a": [round(x + nx * lo_, 2), round(y + ny * lo_, 2)], "b": [round(x + nx * hi_, 2), round(y + ny * hi_, 2)],
                              "t": TRUSS_PIER_M[0], "h": tr_["spring_z"]})
        s0_, s1_ = tr_["s0"], min(tr_["s1"], ln.length)
        n_ = max(2, round((s1_ - s0_) / tr_.get("panel", TRUSS_PANEL_M)))
        mid_, half_ = (s0_ + s1_) / 2, (s1_ - s0_) / 2
        z_top = lambda s_: _h(a["vertical"], s_) - DECK_M
        if "depth" in tr_:          # (a span of one depth, the approach truss over Granville Island)
            z_bot = lambda s_, d_=tr_["depth"]: z_top(s_) - d_
        else:                       # (the arched main span: from its springing points to crown_gap under the deck)
            z_crown = z_top(mid_) - tr_.get("crown_gap", TRUSS_CROWN_M)
            z_bot = lambda s_, zc=z_crown, zs=tr_["spring_z"]: zs + (zc - zs) * (1 - ((s_ - mid_) / half_) ** 2)
        sides_t = {1: [], -1: []}           # each side's panel points: (top, bottom), 1 m in from the deck's edge
        nrm_ = []                           # ... and the axis's normal there, the side planes' normal (n: a lattice member's plane)
        for k in range(n_ + 1):
            s_ = s0_ + (s1_ - s0_) * k / n_
            f_ = planes_(ln, s_)
            if not f_:
                continue
            x, y, nx, ny, t_ = f_
            nrm_.append([round(nx, 3), round(ny, 3)])
            for sd in (1, -1):
                px, py = x + nx * t_[sd], y + ny * t_[sd]
                sides_t[sd].append(([px, py, z_top(s_)], [px, py, z_bot(s_)]))
        # an anchor leg on each side, from a springing point up to the deck ("legs": [[s at its foot, z at its foot, s at the deck]])
        for s_f, z_f, s_d in tr_.get("legs", []):
            for sd in (1, -1):
                ends_ = []
                for s_, z_ in ((s_f, z_f), (s_d, None)):
                    f_ = planes_(ln, s_)
                    if f_:
                        x, y, nx, ny, t_ = f_
                        ends_.append([x + nx * t_[sd], y + ny * t_[sd], z_ if z_ is not None else z_top(s_)])
                if len(ends_) == 2:
                    truss.append({"a": ends_[0], "b": ends_[1], "w": TRUSS_M[0]})
        # a steel bent under the truss at each s of "bents": a lattice leg under each truss plane, from the ground up to the bottom
        # chord, and an X brace between the two legs, all in the plane across the axis (Kaveh, 2026-10-12; photos p1, p0)
        for s_ in tr_.get("bents", []):
            f_ = planes_(ln, s_)
            if not f_:
                continue
            x, y, nx, ny, t_ = f_
            n_x = [round(ny, 3), round(-nx, 3)]
            (l1b, l1t), (l2b, l2t) = [([x + nx * t_[sd], y + ny * t_[sd], 0.0], [x + nx * t_[sd], y + ny * t_[sd], z_bot(s_)]) for sd in (1, -1)]
            truss += [{"a": l1b, "b": l1t, "w": BENT_LEG_M, "n": n_x}, {"a": l2b, "b": l2t, "w": BENT_LEG_M, "n": n_x},
                      {"a": l1b, "b": l2t, "w": TRUSS_M[1], "n": n_x}, {"a": l2b, "b": l1t, "w": TRUSS_M[1], "n": n_x}]
        for pts_ in sides_t.values():
            for k, (top_, bot_) in enumerate(pts_):
                truss.append({"a": top_, "b": bot_, "w": TRUSS_M[1], "n": nrm_[k]})    # the vertical
                if k + 1 < len(pts_):
                    nt_, nb_ = pts_[k + 1]
                    truss.append({"a": top_, "b": nt_, "w": TRUSS_M[0]})               # the chords
                    truss.append({"a": bot_, "b": nb_, "w": TRUSS_M[0]})
                    truss.append({"a": bot_ if k % 2 == 0 else top_, "b": nt_ if k % 2 == 0 else nb_, "w": TRUSS_M[1], "n": nrm_[k]})  # the V
        # the bracing between the two sides (Kaveh, 2026-10-12; the photo under the deck, p3): a top lateral under the deck at each
        # panel point; at every other one a bottom strut and an X across, in the plane of the verticals
        for k, ((t1_, b1_), (t2_, b2_)) in enumerate(zip(sides_t[1], sides_t[-1])):
            n_x = [nrm_[k][1], -nrm_[k][0]]     # (their plane is across the axis: its normal is the axis's direction)
            truss.append({"a": t1_, "b": t2_, "w": TRUSS_M[1], "n": n_x})
            if k % 2 == 0:
                truss += [{"a": b1_, "b": b2_, "w": TRUSS_M[1], "n": n_x}, {"a": t1_, "b": b2_, "w": TRUSS_M[1], "n": n_x},
                          {"a": b1_, "b": t2_, "w": TRUSS_M[1], "n": n_x}]
    for q in truss:
        q["a"], q["b"] = [round(v_, 2) for v_ in q["a"]], [round(v_, 2) for v_ in q["b"]]
    return piers, truss
