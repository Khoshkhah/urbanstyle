"""The roadway from SUMO (docs/design/space-parts.md, "The roadway from SUMO").

duckOSM writes its driving network to SUMO (`duckosm.sumo.to_sumo`: every SUMO edge id is the duckOSM edge_id, the legal turns come
from its edge_graph) with the lane counts and lane widths measured here; SUMO's netconvert builds the lanes, the junction shapes (close
junctions joined into one) and the paths through each junction, and decides which lane goes on to which. All in metres in the UTM zone
of the data.
"""
import logging
import tempfile

log = logging.getLogger("urbanstyle")

NETCONVERT = {"junctions.join": "true",        # a dogleg's or a split road's close nodes are one junction
              "junctions.corner-detail": "8"}  # rounded kerbs at the junction corners


def network(con, edge_attrs, epsg):
    """`edge_attrs`: {edge_id: {sumo edge attribute: value}} for duckOSM's directed driving edges. Returns a dict:
    lanes [(edge, index from the right, lanes of the edge, width, kind driving / bus / bike, [(x, y)])], junctions {id: [(x, y)]},
    ends {edge: (from junction, to junction)}, conns [(from edge, from lane, to edge, to lane, dir, [(x, y)] of the path through the
    junction)], in `epsg` (a UTM zone). None when duckOSM's SUMO export or netconvert is missing or fails, or SUMO did not use our zone:
    the parts are then built without it."""
    import xml.etree.ElementTree as ET
    try:
        from duckosm.sumo import to_sumo
        cur = con.cursor()
        cur.execute("USE osm")
        lanes, junctions, ends, conns, internal, onward = [], {}, {}, [], {}, {}
        with tempfile.TemporaryDirectory() as d:
            zone = int(epsg[-2:])          # our UTM zone, not the one SUMO would pick (they differ near a zone border)
            proj = f"+proj=utm +zone={zone}{' +south' if epsg.startswith('EPSG:327') else ''} +ellps=WGS84 +datum=WGS84 +units=m +no_defs"
            net = to_sumo(cur, d, net_name="roadway", edge_attrs=edge_attrs, config={**NETCONVERT, "proj.utm": "false", "proj": proj})["net"]
            ox = oy = 0.0
            pts = lambda s: [(float(x) - ox, float(y) - oy) for x, y in (p.split(",")[:2] for p in (s or "").split())]
            for _, el in ET.iterparse(net):
                if el.tag == "location":
                    zone = el.get("projParameter", "").split("+zone=")[-1].split()[0]
                    if not epsg.endswith(f"{int(zone):02d}") or ("+south" in el.get("projParameter", "")) != epsg.startswith("EPSG:327"):
                        raise ValueError(f"SUMO used {el.get('projParameter')}, not {epsg}")
                    ox, oy = (float(v) for v in el.get("netOffset").split(","))
                elif el.tag == "edge":
                    ls = el.findall("lane")
                    if el.get("function") == "internal":
                        for la in ls:
                            internal[la.get("id")] = pts(la.get("shape"))
                    elif el.get("function") is None:
                        ends[el.get("id")] = (el.get("from"), el.get("to"))
                        for la in ls:
                            allow = la.get("allow") or ""
                            kind = "bike" if allow == "bicycle" else "bus" if "bus" in allow and "passenger" not in allow else "driving"
                            lanes.append((el.get("id"), int(la.get("index")), len(ls), float(la.get("width") or 3.2), kind, pts(la.get("shape"))))
                    el.clear()
                elif el.tag == "junction" and el.get("type") != "internal" and el.get("shape"):
                    junctions[el.get("id")] = pts(el.get("shape"))
                elif el.tag == "connection":
                    if el.get("from").startswith(":"):     # a path through a junction that goes on through another of its pieces
                        if el.get("via"):
                            onward[f"{el.get('from')}_{el.get('fromLane')}"] = el.get("via")
                    else:
                        conns.append((el.get("from"), int(el.get("fromLane")), el.get("to"), int(el.get("toLane")), el.get("dir"), el.get("via")))
        path = []
        for f, fl, t, tl, dr, via in conns:
            xy, seen = [], set()
            while via and via not in seen:
                seen.add(via)
                xy += internal.get(via, [])
                via = onward.get(via)
            path.append((f, fl, t, tl, dr, xy))
        return dict(lanes=lanes, junctions=junctions, ends=ends, conns=path)
    except Exception as e:
        log.warning(f"no SUMO roadway ({type(e).__name__}: {str(e)[:200]})")
        return None
