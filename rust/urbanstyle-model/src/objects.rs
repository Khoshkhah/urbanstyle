//! The street objects (`urban.object`, docs/design/objects.md): OSM's point features by their tags (`container.OBJECTS`), each in the space
//! and the part that hold it, or the nearest space within `NEAR_M`; the size of its class (`unit.SIZE`). With OSM as the only source every
//! object is its own match (`unit.match` joins objects of different sources). Mapillary and a city's survey are not read.
use geo::{Coord, Distance, Euclidean, Point};
use std::collections::{BTreeMap, HashMap};
use urbanstyle_geo::index::{Index, SegIndex};
use urbanstyle_geo::ops::Mp;

/// A thing outside every space names the nearest space within this distance (`container.OBJECT_NEAR_M`).
pub const NEAR_M: f64 = 60.0;
/// The tags kept as the attributes of an object (`container.OBJECT_ATTRS`).
pub const ATTRS: [&str; 29] = [
    "height", "material", "direction", "angle", "capacity", "lit", "covered", "surface", "ref", "level", "tactile_paving", "kerb", "crossing", "colour", "traffic_sign", "bin", "shelter",
    "bench", "amenity", "highway", "entrance", "barrier", "natural", "operator", "name", "wheelchair", "route_ref", "trolleybus", "public_transport",
];
/// Each class's size, urbanstyle's chosen values: (width, height) in metres (`unit.SIZE`).
pub fn size(class: &str) -> Option<(f64, f64)> {
    Some(match class {
        "furniture.lamp" => (0.22, 7.6),
        "furniture.signal" => (0.16, 3.3),
        "furniture.sign" => (0.65, 2.65),
        "furniture.bench" => (1.8, 0.9),
        "furniture.waste" => (0.5, 1.0),
        "furniture.bollard" => (0.18, 0.9),
        "vegetation.tree" => (0.35, 7.5),
        "transit.stop" => (0.45, 2.7),
        "furniture.post_box" => (0.5, 1.2),
        "furniture.parking_meter" => (0.22, 1.5),
        "furniture.hydrant" => (0.3, 0.8),
        "furniture.water" => (0.3, 1.0),
        "furniture.map_stand" => (1.0, 2.4),
        "furniture.bike_parking" => (2.0, 0.8),
        "furniture.shelter" => (3.0, 2.55),
        "furniture.vending" => (0.8, 1.8),
        "furniture.advertising" => (1.2, 2.2),
        "furniture.charging" => (0.5, 1.5),
        "access.entrance" => (1.2, 2.2),
        "access.parking_entrance" => (3.0, 2.4),
        "barrier.other" => (1.5, 1.0),
        "utility.manhole" | "utility.catch_basin" => (0.6, 0.04),
        "utility.junction_box" => (0.45, 0.04),
        _ => return None,
    })
}

#[derive(Clone)]
pub struct NodeIn {
    pub id: i64,
    pub tags: BTreeMap<String, String>,
    pub xy: Coord<f64>,
}

pub struct ObjectRow {
    pub id: String,
    pub kind: String,
    pub level: i32,
    pub space: Option<String>,
    pub part: Option<String>,
    pub near_m: Option<f64>,
    pub name: Option<String>,
    pub attrs: BTreeMap<String, String>,
    pub width_m: Option<f64>,
    pub width_source: Option<String>,
    pub width_method: Option<String>,
    pub height_m: Option<f64>,
    pub height_source: Option<String>,
    pub height_method: Option<String>,
    pub point: Coord<f64>,
}

/// The class of an OSM node by its tags (the `CASE` of `container.OBJECTS`, in its order), or none.
pub fn class_of(t: &BTreeMap<String, String>) -> Option<&'static str> {
    let g = |k: &str| t.get(k).map(String::as_str);
    let has = |k: &str| t.contains_key(k);
    let is = |k: &str, v: &str| g(k) == Some(v);
    let one_of = |k: &str, vs: &[&str]| g(k).map_or(false, |x| vs.contains(&x));
    Some(if is("highway", "crossing") && (is("crossing", "traffic_signals") || is("crossing:signals", "yes")) {
        "crossing.signalised"
    } else if is("highway", "crossing") && (one_of("crossing", &["zebra", "uncontrolled", "marked"]) || is("crossing_ref", "zebra")) {
        "crossing.zebra"
    } else if is("highway", "crossing") || is("railway", "crossing") {
        "crossing.other"
    } else if is("highway", "traffic_signals") {
        "furniture.signal"
    } else if is("highway", "street_lamp") {
        "furniture.lamp"
    } else if has("traffic_sign") || has("traffic_sign:forward") || one_of("highway", &["stop", "give_way"]) {
        "furniture.sign"
    } else if is("highway", "bus_stop") || one_of("public_transport", &["platform", "stop_position"]) {
        "transit.stop"
    } else if is("amenity", "shelter") {
        "furniture.shelter"
    } else if is("amenity", "bench") || is("leisure", "picnic_table") {
        "furniture.bench"
    } else if one_of("amenity", &["waste_basket", "waste_disposal", "recycling"]) {
        "furniture.waste"
    } else if is("amenity", "bicycle_parking") {
        "furniture.bike_parking"
    } else if one_of("amenity", &["vending_machine", "ticket_validator"]) {
        "furniture.vending"
    } else if is("amenity", "post_box") {
        "furniture.post_box"
    } else if one_of("amenity", &["drinking_water", "fountain"]) || is("man_made", "water_tap") {
        "furniture.water"
    } else if is("amenity", "charging_station") {
        "furniture.charging"
    } else if is("emergency", "fire_hydrant") {
        "furniture.hydrant"
    } else if has("advertising") {
        "furniture.advertising"
    } else if is("barrier", "bollard") {
        "furniture.bollard"
    } else if has("kerb") || is("barrier", "kerb") {
        "kerb.node"
    } else if has("barrier") {
        "barrier.other"
    } else if is("natural", "tree") {
        "vegetation.tree"
    } else if is("amenity", "parking_entrance") {
        "access.parking_entrance"
    } else if has("entrance") {
        "access.entrance"
    } else {
        return None;
    })
}

/// The level in a `level` or `layer` tag: the first whole number in the text, kept to the levels `lo..=hi`; 0 where there is none.
pub fn level_of(t: &BTreeMap<String, String>, lo: i32, hi: i32) -> i32 {
    let s = t.get("level").or_else(|| t.get("layer")).map(|s| s.replace('\u{2212}', "-")).unwrap_or_default();
    let b = s.as_bytes();
    let mut i = 0;
    while i < b.len() {
        let start = i;
        if b[i] == b'-' {
            i += 1;
        }
        let d = b[i..].iter().take_while(|c| c.is_ascii_digit()).count();
        if d > 0 {
            return s[start..i + d].parse::<i64>().map_or(0, |v| v.clamp(lo as i64, hi as i64) as i32);
        }
        i = start + 1;
    }
    0
}

/// A space that can hold an object: its id, its level and its outline.
pub struct SpaceRef<'a> {
    pub id: &'a str,
    pub level: i32,
    pub geom: &'a Mp,
}

/// A part that can hold an object: its id, the space it is in and its outline.
pub struct PartRef<'a> {
    pub id: &'a str,
    pub space: &'a str,
    pub geom: &'a Mp,
}

pub fn build(nodes: &[NodeIn], spaces: &[SpaceRef], parts: &[PartRef], lo: i32, hi: i32) -> Vec<ObjectRow> {
    // (the spaces of each level in one index; the first that holds the point wins, in the order given)
    let mut by_level: BTreeMap<i32, Vec<usize>> = BTreeMap::new();
    for (i, s) in spaces.iter().enumerate() {
        by_level.entry(s.level).or_default().push(i);
    }
    let level_idx: BTreeMap<i32, Index> = by_level.iter().map(|(l, v)| (*l, Index::new(v.iter().map(|&i| geo::BoundingRect::bounding_rect(spaces[i].geom))))).collect();
    let segs: Vec<SegIndex> = spaces.iter().map(|s| SegIndex::new(s.geom)).collect();
    let mut parts_of: HashMap<&str, Vec<usize>> = HashMap::new();
    for (i, p) in parts.iter().enumerate() {
        parts_of.entry(p.space).or_default().push(i);
    }
    let mut out = Vec::new();
    for n in nodes {
        let Some(class) = class_of(&n.tags) else { continue };
        if class.starts_with("crossing.") || class.starts_with("kerb.") {
            continue; // (drawn as the crosswalk and the kerb)
        }
        let level = level_of(&n.tags, lo, hi);
        let p = n.xy;
        let (mut space, mut near) = (None, None);
        if let (Some(ids), Some(ix)) = (by_level.get(&level), level_idx.get(&level)) {
            let r = geo::Rect::new(p, p);
            let mut hits = ix.query(&r);
            hits.sort();
            space = hits.into_iter().map(|k| ids[k]).find(|&i| segs[i].contains(p));
            if space.is_none() {
                let grown = geo::Rect::new(Coord { x: p.x - NEAR_M, y: p.y - NEAR_M }, Coord { x: p.x + NEAR_M, y: p.y + NEAR_M });
                let best = ix
                    .query(&grown)
                    .into_iter()
                    .map(|k| ids[k])
                    .map(|i| (Euclidean.distance(spaces[i].geom, &Point::from(p)), spaces[i].id))
                    .filter(|x| x.0 <= NEAR_M)
                    .min_by(|a, b| a.partial_cmp(b).unwrap());
                if let Some((d, id)) = best {
                    near = Some((d * 100.0).round_ties_even() / 100.0);
                    space = ids.iter().copied().find(|&i| spaces[i].id == id);
                }
            }
        }
        let inside = space.is_some() && near.is_none();
        let part = space.filter(|_| inside).and_then(|i| {
            parts_of.get(spaces[i].id).and_then(|v| v.iter().find(|&&k| geo::Contains::contains(parts[k].geom, &Point::from(p)))).map(|&k| parts[k].id.to_string())
        });
        let sz = size(class);
        out.push(ObjectRow {
            id: format!("n{}", n.id),
            kind: class.into(),
            level,
            space: space.map(|i| spaces[i].id.to_string()),
            part,
            near_m: near,
            name: n.tags.get("name").cloned(),
            attrs: n.tags.iter().filter(|(k, _)| ATTRS.contains(&k.as_str())).map(|(k, v)| (k.clone(), v.clone())).collect(),
            width_m: sz.map(|s| s.0),
            width_source: sz.map(|_| "urbanstyle".to_string()),
            width_method: sz.map(|_| "chosen".to_string()),
            height_m: sz.map(|s| s.1),
            height_source: sz.map(|_| "urbanstyle".to_string()),
            height_method: sz.map(|_| "chosen".to_string()),
            point: p,
        });
    }
    out
}
