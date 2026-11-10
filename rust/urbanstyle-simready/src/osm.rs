//! OSM's ways and nodes from duckOSM's raw files (`raw_ways.parquet`: tags, refs and the line as WKB; `raw_nodes.parquet`), in UTM metres.
//! The pedestrian ways the steps read (the Python `work.element` rows of type walkway): the crossings of the division and the paths
//! of the blocks step. duckOSM's walking graph also holds virtual edges (a negative id, the way of the same id without the minus,
//! through an open pedestrian area); the pass-0 folder does not hold the walking graph, so those paths are not read.
use crate::{table::Table, wkb};
use geo::{BoundingRect, Coord, Intersects, LineString, MultiLineString};
use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;
use urbanstyle_blocks::PathWay;
use urbanstyle_division::{CrossingNode, CrossingWay};
use urbanstyle_geo::ops::Mp;
use urbanstyle_geo::utm;

pub struct Way {
    pub id: i64,
    pub refs: Vec<i64>,
    pub tags: BTreeMap<String, String>,
    pub lines: Vec<LineString<f64>>,
}

/// The highway values of duckOSM's walking graph that matter here.
const WALKING: [&str; 7] = ["footway", "path", "pedestrian", "steps", "cycleway", "bridleway", "corridor"];
/// The classes of a pedestrian way that cuts the blocks (`blocks.path_sql`).
const PATH_CLASSES: [&str; 4] = ["pedestrian", "footway", "steps", "path"];

fn tags_of(t: &Table, col: &str) -> Vec<BTreeMap<String, String>> {
    t.map_strs(col).into_iter().map(|m| m.unwrap_or_default()).collect()
}

/// The ways of `raw_ways.parquet` in `zone`.
pub fn ways(path: &Path, zone: u32) -> Result<Vec<Way>, String> {
    let t = Table::open(path)?;
    let (id, tags, line, refs) = (t.i64s("osm_id"), tags_of(&t, "tags"), t.blobs("line"), t.list_i64s("refs"));
    let mut out = Vec::new();
    for i in 0..id.len() {
        let (Some(id), Some(b)) = (id[i], line[i].as_ref()) else { continue };
        let Some(wkb::Geom::Lines(ls)) = wkb::parse(b) else { continue };
        let lines = ls.into_iter().map(|l| LineString::new(l.0.iter().map(|c| { let (x, y) = utm::forward(c.x, c.y, zone); Coord { x, y } }).collect())).collect();
        out.push(Way { id, refs: refs[i].clone().unwrap_or_default(), tags: tags[i].clone(), lines });
    }
    Ok(out)
}

/// One driving edge of duckOSM's graph (the twins of a two-way road are two edges).
pub struct DrivingEdge {
    pub osm_id: i64,
    pub source: i64,
    pub target: i64,
    pub name: Option<String>,
    pub oneway: bool,
    pub level: i64,
    pub line: LineString<f64>,
}

/// The driving edges in `zone`, with the level of each (`container.ROADS`: the `layer` tag, else 1 for a bridge, -1 for a tunnel, else 0).
pub fn driving_edges(path: &Path, zone: u32) -> Result<Vec<DrivingEdge>, String> {
    let t = Table::open(path)?;
    let (osm, source, target, name, layer, bridge, tunnel, geom, oneway) = (t.i64s("osm_id"), t.i64s("source"), t.i64s("target"), t.strs("name"), t.strs("layer"), t.strs("bridge"), t.strs("tunnel"), t.blobs("geometry"), t.bools("oneway"));
    let mut out = Vec::new();
    for i in 0..osm.len() {
        let (Some(o), Some(s), Some(g), Some(b)) = (osm[i], source[i], target[i], geom[i].as_ref()) else { continue };
        let Some(wkb::Geom::Lines(mut ls)) = wkb::parse(b) else { continue };
        if ls.len() != 1 {
            continue;
        }
        let set = |v: &Option<String>| v.as_deref().map_or(false, |x| x != "no");
        let level = layer[i].as_deref().and_then(|l| l.trim().parse::<i64>().ok()).unwrap_or(if set(&bridge[i]) { 1 } else if set(&tunnel[i]) { -1 } else { 0 });
        out.push(DrivingEdge { osm_id: o, source: s, target: g, name: name[i].clone(), oneway: oneway[i].unwrap_or(false), level, line: crate::proj::line(&ls.pop().unwrap(), zone) });
    }
    Ok(out)
}

/// The OSM ids of duckOSM's driving edges: a way a car can use is a road, not a walkway.
pub fn driving_ways(edges_path: &Path) -> Result<BTreeSet<i64>, String> {
    Ok(Table::open(edges_path)?.i64s("osm_id").into_iter().flatten().collect())
}

/// `container.ROADS`: the level of a way: its `layer` tag, else 1 for a bridge, -1 for a tunnel, else 0.
fn level(w: &Way) -> i64 {
    if let Some(l) = w.tags.get("layer").and_then(|l| l.trim().parse::<i64>().ok()) {
        return l;
    }
    let set = |k: &str| w.tags.get(k).map_or(false, |v| v != "no");
    if set("bridge") { 1 } else if set("tunnel") { -1 } else { 0 }
}

/// A walking way: not one that cars use, not inside a car park or into a property, a footpath's highway value.
fn walking(w: &Way, driving: &BTreeSet<i64>) -> bool {
    w.tags.get("highway").map_or(false, |h| WALKING.contains(&h.as_str()))
        && !driving.contains(&w.id)
        && !matches!(w.tags.get("service").map(String::as_str), Some("parking_aisle") | Some("driveway"))
}

fn reaches(area: &Mp, lines: &[LineString<f64>]) -> bool {
    lines.iter().any(|l| l.bounding_rect().is_some() && area.intersects(l))
}

/// The walking ways at level 0 (the pedestrian and cycle ways that are no road).
pub fn walking_ways<'a>(ways: &'a [Way], driving: &BTreeSet<i64>) -> Vec<&'a Way> {
    ways.iter().filter(|w| walking(w, driving) && level(w) == 0).collect()
}

/// The crossings at level 0 (`footway=crossing`, or `highway=crossing` on the way), with their tags.
pub fn crossing_ways(ways: &[Way], driving: &BTreeSet<i64>, area: &Mp) -> Vec<CrossingWay> {
    ways.iter()
        .filter(|w| walking(w, driving) && level(w) == 0 && (w.tags.get("footway").map(String::as_str) == Some("crossing") || w.tags.get("highway").map(String::as_str) == Some("crossing")))
        .filter(|w| reaches(area, &w.lines))
        .map(|w| CrossingWay { id: w.id, lines: w.lines.clone(), tags: w.tags.clone() })
        .collect()
}

/// The pedestrian ways that cut the blocks (`blocks.path_sql`): level 0, not a crossing or a sidewalk, not a pedestrian area.
pub fn paths(ways: &[Way], driving: &BTreeSet<i64>, area: &Mp) -> Vec<PathWay> {
    ways.iter()
        .filter(|w| walking(w, driving) && level(w) == 0)
        .filter(|w| w.tags.get("highway").map_or(false, |h| PATH_CLASSES.contains(&h.as_str())))
        .filter(|w| !matches!(w.tags.get("footway").map(String::as_str), Some("crossing") | Some("sidewalk")))
        .filter(|w| w.tags.get("area").map_or(true, |a| a != "yes"))
        .filter(|w| reaches(area, &w.lines))
        .map(|w| PathWay {
            way: w.id,
            class: w.tags["highway"].clone(),
            name: w.tags.get("name").cloned(),
            geom: MultiLineString::new(w.lines.clone()),
            width: w.tags.get("width").and_then(|x| x.trim().parse::<f64>().ok()),
        })
        .collect()
}

/// The nodes tagged `highway=crossing`, in `zone`.
pub fn crossing_nodes(path: &Path, zone: u32) -> Result<Vec<CrossingNode>, String> {
    let t = Table::open(path)?;
    let (id, lat, lon, tags) = (t.i64s("osm_id"), t.f64s("lat"), t.f64s("lon"), tags_of(&t, "tags"));
    Ok((0..id.len())
        .filter(|&i| tags[i].get("highway").map(String::as_str) == Some("crossing"))
        .filter_map(|i| {
            let (x, y) = utm::forward(lon[i]?, lat[i]?, zone);
            Some(CrossingNode { id: id[i]?, tags: tags[i].clone(), xy: Coord { x, y } })
        })
        .collect())
}

/// The tags that make a node a street object, or that the object rules read (`container.OBJECT_ATTRS` and the keys of the rules).
pub const OBJECT_KEYS: &[&str] = &[
    "advertising", "amenity", "angle", "barrier", "bench", "bin", "capacity", "colour", "covered", "crossing", "crossing:signals", "crossing_ref", "direction", "emergency", "entrance", "height", "highway", "kerb", "layer", "leisure", "level", "lit", "man_made", "material", "name", "natural", "operator", "public_transport", "railway", "ref", "route_ref", "shelter", "surface", "tactile_paving", "traffic_sign", "traffic_sign:forward", "trolleybus", "wheelchair", ", ", ", ", ", ", ", ", ", ", ", ", ", ", ", ", ", ",
];

/// The nodes that carry any of the object keys, with only those tags, in `zone` (`rust/tools/export_object_fixture.py`).
pub fn object_nodes(path: &Path, zone: u32) -> Result<Vec<urbanstyle_model::objects::NodeIn>, String> {
    let t = Table::open(path)?;
    let (id, lat, lon, tags) = (t.i64s("osm_id"), t.f64s("lat"), t.f64s("lon"), tags_of(&t, "tags"));
    let mut out = Vec::new();
    for i in 0..id.len() {
        let kept: BTreeMap<String, String> = tags[i].iter().filter(|(k, _)| OBJECT_KEYS.contains(&k.as_str())).map(|(k, v)| (k.clone(), v.clone())).collect();
        if kept.is_empty() {
            continue;
        }
        let (Some(id), Some(x), Some(y)) = (id[i], lon[i], lat[i]) else { continue };
        let (e, n) = utm::forward(x, y, zone);
        out.push(urbanstyle_model::objects::NodeIn { id, tags: kept, xy: Coord { x: e, y: n } });
    }
    Ok(out)
}

/// The place of each node that a driving edge starts or ends at (`source` and `target`), in `zone`: the first and last point of the edges.
pub fn node_points(edges: &[DrivingEdge]) -> BTreeMap<i64, Coord<f64>> {
    let mut out = BTreeMap::new();
    for e in edges {
        if let (Some(a), Some(b)) = (e.line.0.first(), e.line.0.last()) {
            out.insert(e.source, *a);
            out.insert(e.target, *b);
        }
    }
    out
}

/// The width in the `width` tag of each way (`w<id>` to metres): the first number in the text, as `regexp_extract(tags['width'], '[0-9.]+')`.
pub fn way_widths(ways: &[Way]) -> BTreeMap<String, f64> {
    let first_number = |t: &str| -> Option<f64> {
        let start = t.find(|c: char| c.is_ascii_digit() || c == '.')?;
        let num: String = t[start..].chars().take_while(|c| c.is_ascii_digit() || *c == '.').collect();
        num.parse().ok()
    };
    ways.iter().filter_map(|w| Some((format!("w{}", w.id), first_number(w.tags.get("width")?)?))).filter(|(_, v)| *v != 0.0).collect()
}

/// The lines of the driving edges that are part of a roundabout or a circle (`junction=roundabout` or `circular`).
pub fn roundabouts(edges: &[DrivingEdge], ways: &[Way], area: &Mp) -> Vec<LineString<f64>> {
    let ring: BTreeSet<i64> = ways.iter().filter(|w| matches!(w.tags.get("junction").map(String::as_str), Some("roundabout") | Some("circular"))).map(|w| w.id).collect();
    // (only those in the area: the Python reads a database cut to the area, duckOSM's file holds the whole region)
    edges.iter().filter(|e| ring.contains(&e.osm_id) && area.intersects(&e.line)).map(|e| e.line.clone()).collect()
}
