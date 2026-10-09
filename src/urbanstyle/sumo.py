"""Lane-level turns at junctions from SUMO (docs/design/space-parts.md, "Turns").

duckOSM writes its driving network to SUMO (`duckosm.sumo.to_sumo`, every SUMO edge id is the duckOSM edge_id, the legal turns come
from its edge_graph) with the lane counts and lane widths measured here; SUMO's netconvert then decides which lane of a road goes on
to which lane of the next. They come back as {(edge_id, lane): [(edge_id, lane)]}, lane 0 the rightmost, and the number of lanes of
every edge.
"""
import logging
import tempfile

log = logging.getLogger("urbanstyle")


def connections(con, edge_attrs):
    """`edge_attrs`: {edge_id: {"numLanes": n, "width": m}} for duckOSM's directed driving edges. Returns (connections, lanes per
    edge), or (None, None) when duckOSM's SUMO export or netconvert is missing or fails: the parts are then built without them."""
    import xml.etree.ElementTree as ET
    try:
        from duckosm.sumo import to_sumo
        cur = con.cursor()
        cur.execute("USE osm")
        conns, lanes = {}, {}
        with tempfile.TemporaryDirectory() as d:
            net = to_sumo(cur, d, net_name="turns", edge_attrs=edge_attrs)["net"]
            for _, el in ET.iterparse(net):
                if el.tag == "edge" and el.get("function") is None:
                    lanes[el.get("id")] = len(el.findall("lane"))
                    el.clear()
                elif el.tag == "connection" and not el.get("from").startswith(":"):     # ":..." are SUMO's own paths inside a junction
                    conns.setdefault((el.get("from"), int(el.get("fromLane"))), []).append((el.get("to"), int(el.get("toLane"))))
        return conns, lanes
    except Exception as e:
        log.warning(f"no SUMO turns ({type(e).__name__}: {str(e)[:200]})")
        return None, None
