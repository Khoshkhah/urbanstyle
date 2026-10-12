"""A bridge profile (docs/design/bridge-profile.md) drawn by bridge3d.model: heights from the vertical profile, one ribbon per band,
the painted lines between the lanes."""
from urbanstyle.bridge3d import model

X, Y = 500000.0, 5000000.0      # a point in UTM zone 10


def _profile():
    val = lambda v: {"value": v, "source": "test", "method": "chosen"}
    lane = lambda d, t: {"type": "lane", "direction": d, "lane": 1, "t": t, "width": val(3.25), "source": "test", "method": "chosen"}
    return {"format": "urbanstyle.bridge/1", "name": "Test Bridge", "crs": "EPSG:32610",
            "deck": {"outline": val([[X, Y - 10], [X + 100, Y - 10], [X + 100, Y + 10], [X, Y + 10], [X, Y - 10]]),
                     "thickness": val(1.0), "parapet": val(1.1)},
            "axes": [{"id": "a1", "line": val([[X, Y], [X + 100, Y]]), "length_m": 100.0,
                      "vertical": {"points": [[0.0, 0.0], [48.0, 10.0], [100.0, 0.0]], "source": "test", "method": "chosen"},
                      "sections": [{"s0": 0.0, "s1": 100.0, "bands": [lane("backward", 1.625), lane("forward", -1.625)]}]}],
            "piers": [{"axis": "a1", "s": 48.0, "width": 1.5, "source": "test", "method": "chosen"}]}


def test_model_follows_the_profile():
    m = model(_profile())
    assert max(v[2] for v in m["verts"]) == 11.1                  # the deck's top at s = 48 (10 m) plus the parapet
    assert len(m["lanes"]) == 2
    mid = [p for p in m["lanes"][0]["l"] if abs(p[0] - (48 - 50)) < 0.01]  # the origin is the middle of the outline: x - (X + 50), y - Y
    assert mid and mid[0][2] == 10.05 and mid[0][1] == 3.25          # the backward lane's left edge, 0.05 m above the deck at s = 48
    assert sorted(l["kind"] for l in m["lines"]) == ["centre line", "edge line", "edge line"]
    assert m["piers"] and m["piers"][0]["h"] == 9.0               # down from the deck's bottom


def test_a_landing_meets_the_street():
    """Where the deck lands (height 0), nothing of it lies under the ground and its parapet ends: on the flat map a slab under the ground
    showed as a block standing on the street."""
    m = model(_profile())
    assert min(v[2] for v in m["verts"]) == 0.0
    ends = [v for v in m["verts"] if abs(v[0] + 50) < 0.1]           # the deck's start (map metres: UTM scale 0.9996 here)
    assert ends and max(v[2] for v in ends) == 0.0


def test_no_guard_across_a_road_that_reaches_the_ground():
    """Where an axis reaches the ground, no guard stands across the deck's end, also outside its lanes (pieces were left between the
    lanes and the deck's corners, as blocks on the road)."""
    P = _profile()
    P["axes"][0]["ends"] = [{"s": 0.0, "ground": True}, {"s": 100.0, "ground": True}]
    guard = [v for sf in model(P)["surf"] if sf["key"] in ("barrier", "railing") for v in sf["v"]]
    assert guard and not [v for v in guard if abs(v[0]) > 49.0 and abs(v[1]) < 9.0]


def test_lanes_end_at_a_mapped_path_and_carry_arrows():
    """Lanes whose chosen widths reach over a footway OSM maps beside them narrow to end at it (the count stays); every lane has an
    arrow."""
    P = _profile()
    P["paths"] = [{"way": "w1", "type": "footway", "line": [[X, Y - 3.5], [X + 100, Y - 3.5]], "footway": "sidewalk",
                   "width": {"value": 2.0, "source": "test", "method": "chosen"}, "source": "test", "method": "mapped"}]
    m = model(P)
    fwd = [l["props"] for l in m["lanes"] if l["props"].get("direction") == "forward"][0]
    assert fwd["width_m"] == 2.75 and "narrowed" in fwd["width_method"]          # to the path's inner edge (2.5 m), but not under LANE_MIN_M
    assert [l["props"] for l in m["lanes"] if l["props"].get("direction") == "backward"][0]["width_m"] == 3.25
    assert sum(sf["key"] == "mark arrow" for sf in m["surf"]) >= 2 * 2     # a shaft and a head in each of the two lanes


def test_model_checks_pass_on_a_plain_bridge():
    """The bridge checks (BR1-BR8) find nothing wrong on a plain deck, and say where they look."""
    rows = model(_profile())["checks"]
    assert [r[0] for r in rows] == [f"BR{i}" for i in range(1, 9)]
    assert not [r for r in rows if r[3] and r[2]]
