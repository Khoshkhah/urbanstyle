//! The input of the ground step from duckOSM's files (what `ground.gather` reads from `osm.features.*`, the raw ways and the driving
//! graph): the kinds in the order they take the ground, with the items that OSM gives, and the road and path lines the left-over ground is
//! traced to. The street, the corridors of the paths, the structures of the streets and the buildings come from the steps before; their
//! kinds are here with no items, in their place of the order.
use crate::{osm, proj, table::Table, wkb};
use geo::{LineString, MultiLineString};
use std::collections::BTreeMap;
use std::path::Path;
use urbanstyle_ground::{Item, Kind, Line};
use urbanstyle_geo::ops::{self, Mp};

const PUBLIC_GREEN: [&str; 9] = ["park", "playground", "pitch", "recreation_ground", "wood", "forest", "cemetery", "nature_reserve", "dog_park"];
const OTHER_GREEN: [&str; 8] = ["grass", "garden", "allotments", "meadow", "village_green", "scrub", "flowerbed", "greenfield"];
const SQUARE_LAND: [&str; 3] = ["pedestrian", "square", "plaza"];
/// A driveway's apron where OSM gives no width (`parts.DRIVEWAY_M`).
const DRIVEWAY_M: f64 = 3.5;

pub struct GroundIn {
    pub order: Vec<Kind>,
    pub lines: Vec<Line>,
}

fn kind(typ: &str, source: &str, method: &str, items: Vec<Item>) -> Kind {
    Kind { typ: typ.into(), source: source.into(), method: method.into(), items }
}

struct Feature {
    osm_type: String,
    id: Option<i64>,
    kind: String,
    name: Option<String>,
    geom: Mp,
}

fn features(path: &Path, zone: u32) -> Result<Vec<Feature>, String> {
    let t = Table::open(path)?;
    let (ty, id, kind, name, geom) = (t.strs("osm_type"), t.i64s("osm_id"), t.strs("kind"), t.strs("name"), t.blobs("geom"));
    let mut out = Vec::new();
    for i in 0..id.len() {
        let Some(b) = geom[i].as_ref() else { continue };
        let Some(wkb::Geom::Polys(m)) = wkb::parse(b) else { continue };
        // (the sea has no OSM id: Python writes its reference as `rNone`)
        out.push(Feature { osm_type: ty[i].clone().unwrap_or_default(), id: id[i], kind: kind[i].clone().unwrap_or_default(), name: name[i].clone(), geom: proj::polys(&m, zone) });
    }
    Ok(out)
}

fn num(id: Option<i64>) -> String {
    id.map_or("None".into(), |i| i.to_string())
}

fn way_ref(f: &Feature) -> String {
    format!("{}{}", if f.osm_type == "way" { "w" } else { "r" }, num(f.id))
}

/// `dir` holds the `features-<name>.parquet` files, `pass0` duckOSM's pass-0 folder. `lots` are the off-street car parks.
pub fn read(dir: &Path, pass0: &Path, zone: u32, lots: &[urbanstyle_model::elements::LotIn]) -> Result<GroundIn, String> {
    let ways = osm::ways(&pass0.join("raw_ways.parquet"), zone)?;
    // (not an area OSM maps under the ground, layer < 0: Monaco's station is in a tunnel)
    let below: std::collections::BTreeSet<i64> = ways.iter().filter(|w| w.tags.get("layer").and_then(|l| l.trim().parse::<i64>().ok()).map_or(false, |l| l < 0)).map(|w| w.id).collect();
    let land = features(&dir.join("features-land.parquet"), zone)?;
    let of_kinds = |kinds: &[&str]| -> Vec<Item> {
        land.iter()
            .filter(|f| kinds.contains(&f.kind.as_str()) && !(f.osm_type == "way" && f.id.map_or(false, |i| below.contains(&i))))
            .map(|f| Item { r#ref: way_ref(f), name: f.name.clone(), geom: f.geom.clone() })
            .collect()
    };
    let sites = features(&dir.join("features-sites.parquet"), zone)?;
    let sites_of = |k: &str| -> Vec<Item> { sites.iter().filter(|f| f.kind == k).map(|f| Item { r#ref: format!("w{}", num(f.id)), name: f.name.clone(), geom: f.geom.clone() }).collect() };

    // ---- the water: OSM's polygons and the sea (duckOSM's `ocean`, made from the coastline)
    let mut water: Vec<Item> = features(&dir.join("features-water_polygons.parquet"), zone)?.iter().map(|f| Item { r#ref: format!("w{}", num(f.id)), name: f.name.clone(), geom: f.geom.clone() }).collect();
    water.extend(features(&dir.join("features-ocean.parquet"), zone)?.iter().map(|f| Item { r#ref: way_ref(f), name: Some(f.name.clone().unwrap_or_else(|| "sea".into())), geom: f.geom.clone() }));

    // ---- the squares: OSM's land of that kind and the pedestrian areas drawn as a closed way (highway=pedestrian, area=yes)
    let mut square = of_kinds(&SQUARE_LAND);
    for w in &ways {
        let t = &w.tags;
        let level0 = t.get("layer").and_then(|l| l.trim().parse::<i64>().ok()).unwrap_or(0) == 0;
        if t.get("highway").map(String::as_str) == Some("pedestrian") && t.get("area").map(String::as_str) == Some("yes") && level0 && w.lines.len() == 1 {
            let l = &w.lines[0];
            if l.0.len() >= 4 && l.0.first() == l.0.last() {
                square.push(Item { r#ref: format!("w{}", w.id), name: t.get("name").cloned(), geom: Mp::new(vec![geo::Polygon::new(l.clone(), vec![])]) });
            }
        }
    }

    // ---- the driveways: OSM's driving edges of a way tagged service=driveway, as wide as OSM says, else DRIVEWAY_M
    let edges = osm::driving_edges(&pass0.join("edges_driving.parquet"), zone)?;
    let way_by_id: BTreeMap<i64, &osm::Way> = ways.iter().map(|w| (w.id, w)).collect();
    let mut by_way: BTreeMap<i64, Vec<&LineString<f64>>> = BTreeMap::new();
    for e in &edges {
        let Some(w) = way_by_id.get(&e.osm_id) else { continue };
        let t = &w.tags;
        if t.get("service").map(String::as_str) == Some("driveway") && t.get("layer").map_or(true, |l| l == "0") && t.get("tunnel").map_or(true, |x| x == "no") {
            by_way.entry(e.osm_id).or_default().push(&e.line);
        }
    }
    let drives: Vec<Item> = by_way
        .iter()
        .map(|(id, ls)| {
            let w = way_by_id[id];
            let half = w.tags.get("width").and_then(|x| x.trim().parse::<f64>().ok()).unwrap_or(DRIVEWAY_M) / 2.0;
            // (the twin of a two-way driveway is the same line the other way round: once. The Python buffers the union of the lines, which
            // dissolves it, and keeps the pieces apart: the caps are flat where they meet)
            let mut once: Vec<LineString<f64>> = Vec::new();
            for l in ls {
                let mut r = (*l).clone();
                r.0.reverse();
                if !once.iter().any(|x| x == *l || *x == r) {
                    once.push((*l).clone());
                }
            }
            let merged = once;
            let bands: Vec<Mp> = merged.iter().map(|l| ops::buffer_line_flat(l, half)).collect();
            Item { r#ref: format!("w{id}"), name: w.tags.get("name").cloned(), geom: ops::union_all(bands.iter()) }
        })
        .collect();

    // ---- the order the kinds take the ground (the blocks first)
    let car_parks: Vec<Item> = lots.iter().map(|l| Item { r#ref: l.id.clone(), name: l.name.clone(), geom: l.geom.clone() }).collect();
    let order = vec![
        kind("street", "urbanstyle", "derived", vec![]),
        kind("path", "urbanstyle", "derived", vec![]),
        kind("building", "osm", "mapped", vec![]),
        kind("water", "osm", "mapped", water),
        kind("rail", "osm", "mapped", of_kinds(&["railway"])),
        kind("square", "osm", "mapped", square),
        kind("structure", "osm", "mapped", sites_of("bridge")),
        kind("green", "osm", "mapped", of_kinds(&PUBLIC_GREEN)),
        kind("car park", "osm", "mapped", car_parks),
        kind("construction site", "osm", "mapped", sites_of("construction")),
        kind("alley", "osm", "mapped", drives),
        kind("green", "osm", "mapped", of_kinds(&OTHER_GREEN)),
        kind("structure", "urbanstyle", "derived", vec![]),
    ];

    // ---- the lines the left-over ground is traced to: the roads at level 0 (one for each driving edge, twins once), the walking ways
    let mut lines: Vec<Line> = Vec::new();
    let mut seen: std::collections::BTreeSet<(i64, i64, i64)> = std::collections::BTreeSet::new();
    for e in edges.iter().filter(|e| e.level == 0) {
        if !seen.insert((e.osm_id, e.source.min(e.target), e.source.max(e.target))) {
            continue;
        }
        let w = way_by_id.get(&e.osm_id);
        if w.map_or(false, |w| matches!(w.tags.get("service").map(String::as_str), Some("parking_aisle") | Some("driveway"))) {
            continue;
        }
        lines.push(Line {
            typ: "road".into(),
            r#ref: format!("w{}", e.osm_id),
            name: e.name.clone(),
            lines: vec![e.line.clone()],
            width: w.and_then(|w| w.tags.get("width")).and_then(|x| x.trim().parse::<f64>().ok()),
        });
    }
    let driving = osm::driving_ways(&pass0.join("edges_driving.parquet"))?;
    for w in osm::walking_ways(&ways, &driving) {
        lines.push(Line {
            typ: "walkway".into(),
            r#ref: format!("w{}", w.id),
            name: w.tags.get("name").cloned(),
            lines: w.lines.clone(),
            width: w.tags.get("width").and_then(|x| x.trim().parse::<f64>().ok()),
        });
    }
    let _ = MultiLineString::<f64>::new(vec![]);
    Ok(GroundIn { order, lines })
}
