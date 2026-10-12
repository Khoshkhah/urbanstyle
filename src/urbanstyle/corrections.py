"""Corrections to OSM where OSM is wrong and no source we read says better (corrections/lanes.json): {"w<way>": {tag: value, ...,
"note": why and from what}}. The tags replace OSM's for that way wherever lanes are counted (the bridge profile, the division); every
value they set names SOURCE, never "osm"."""
import json
import os

PATH = os.path.join(os.path.dirname(__file__), "..", "..", "corrections", "lanes.json")
SOURCE = "urbanstyle corrections (corrections/lanes.json)"


def lanes():
    """{OSM way id: (the tags to set, as strings; the note)}; {} where there is no file."""
    try:
        d = json.load(open(PATH))
    except FileNotFoundError:
        return {}
    return {int(k.lstrip("w")): ({t: str(v) for t, v in x.items() if t != "note"}, x.get("note", "")) for k, x in d.items()}


def per_direction(tags, oneway):
    """(lanes along the way, lanes against it) that corrected tags give."""
    if oneway:
        return int(tags["lanes"]), 0
    n = int(tags["lanes"])
    f, b = tags.get("lanes:forward"), tags.get("lanes:backward")
    return (int(f) if f else n - n // 2), (int(b) if b else n // 2)


def bridge(name):
    """A bridge's corrections (corrections/bridges.json): e.g. {"median": "barrier", "note": ...}; {} if none."""
    try:
        return json.load(open(os.path.join(os.path.dirname(PATH), "bridges.json"))).get(name, {})
    except FileNotFoundError:
        return {}
