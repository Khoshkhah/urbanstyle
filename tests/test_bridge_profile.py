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
    ends = [v for v in m["verts"] if abs(v[0] + 50) < 0.01]          # the deck's start, where the vertical profile is 0
    assert ends and max(v[2] for v in ends) == 0.0
