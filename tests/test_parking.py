from urbanstyle.mapillary import group
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
