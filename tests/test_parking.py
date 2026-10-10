import shapely

from urbanstyle.mapillary import group
from urbanstyle.parts import strip_size
from urbanstyle.unit import van_meter_rule


def test_meter_rule_and_sign_groups():
    meter = {"rate_9am_6pm": "$4.50", "time_limit_9am_6pm": "2 Hr", "rate_6pm_10pm": "$1.50", "time_limit_6pm_10pm": "4 Hr",
             "am_rush_hours": "7am-9am M-F", "vehicle_type": "Any Vehicle"}
    assert van_meter_rule(meter) == "pay $4.50/h 9am-6pm (2 Hr), $1.50/h 6pm-10pm (4 Hr); no parking rush hours 7am-9am M-F"
    assert van_meter_rule({}) == "pay (rates not given)"
    # a sign's variants are one group; a meter is not a sign
    assert group("regulatory--no-parking--g9") == group("regulatory--no-stopping--g1") == "no parking"
    assert group("information--parking--g3") == "parking"
    assert group("object--parking-meter") == "parking meter"


def test_strip_size():
    w, length = strip_size(shapely.box(0, 0, 40, 2.5))           # a sidewalk strip 40 m by 2.5 m
    assert round(w, 6) == 2.5 and round(length, 6) == 40
    bend = shapely.LineString([(0, 0), (30, 0), (30, 30)]).buffer(1.5, cap_style="flat", join_style="mitre")   # bending round a corner
    assert abs(strip_size(bend)[0] - 3.0) < 0.05
    assert round(strip_size(shapely.box(0, 0, 5, 5))[0], 6) == 5        # a square
