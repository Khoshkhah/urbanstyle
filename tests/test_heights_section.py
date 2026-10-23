"""The heights section of a bridge profile (docs/notes/bridge-heights.md): one height at a junction (an OSM node) and one at the middle
of a branch, from a heights file. Offline."""
from urbanstyle.bridge_heights import apply, from_vertical


def _profile():
    line = {"value": [[0.0, 0.0], [100.0, 0.0]]}
    return {"name": "B", "axes": [{"id": "a1", "ways": ["w1"], "line": line, "length_m": 100.0,
                                   "ends": [{"s": 0.0, "ground": True, "node": "n1"}, {"s": 100.0, "ground": False, "node": "n2"}],
                                   "vertical": {"points": [[0, 0], [100, 6]], "source": "urbanstyle", "method": "chosen"}}]}


def test_a_junction_and_a_branch_middle_become_entries():
    P = apply(_profile(), {"n2": 8.0, "a1": 5.0})
    assert P["heights"]["n2"] == {"deck_m": 8.0, "source": "heights file", "method": "chosen"}
    assert P["heights"]["a1"]["mid_m"] == 5.0


def test_a_measured_vertical_becomes_its_points():
    P = _profile()
    P["axes"][0]["vertical"].update(source="LiDAR", method="measured", curves=[0, 0])
    assert from_vertical(P)["heights"]["a1"]["points"] == [[0, 0], [100, 6]]
