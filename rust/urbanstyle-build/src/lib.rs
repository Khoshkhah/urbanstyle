//! The whole build in one chain, from the raw inputs to the tables: the blocks, the division, the ground, the paths, the model, the
//! building and lot rows, the street objects, the checks, the registry and the tables of the page. Each step takes what the step before it
//! made; nothing goes through Python. The raw inputs (SimReady's tables, duckOSM's features) are read from JSON files that the Python
//! exporters wrote (`read`), until the readers of the tables themselves (Parquet or Arrow) are written.
pub mod read;

use geo::{Coord, LineString};
use serde_json::Value;
use std::collections::BTreeMap;
use std::path::Path;
use urbanstyle_geo::{io, ops, ops::Mp};

/// The grid the parts are snapped to (`simready.py`'s `clean`), and the smallest part kept.
pub const GRID_M: f64 = 0.01;
pub const MIN_PART_M2: f64 = 0.05;

/// A polygon with the slits narrower than the grid closed (the parts of a space are cut by separate overlays: where they meet, the
/// edges are less than a grid apart, and the union of them keeps the slit).
fn close(m: &Mp) -> Mp {
    ops::snap(&ops::buffer_mitre(&ops::buffer_mitre(m, GRID_M / 2.0), -GRID_M / 2.0), GRID_M)
}

pub struct Built {
    pub model: urbanstyle_model::Output,
    pub elements: Vec<urbanstyle_model::elements::ElementRow>,
    pub objects: Vec<urbanstyle_model::objects::ObjectRow>,
    pub surfaces: Vec<urbanstyle_ground::surfaces::Surface>,
    pub checks: Vec<urbanstyle_checks::Check>,
    pub things: Vec<urbanstyle_model::registry::Thing>,
    pub registry: Vec<urbanstyle_model::registry::Registered>,
    pub uids: BTreeMap<(&'static str, String), String>,
    /// (step, seconds)
    pub timings: Vec<(String, f64)>,
}

fn os(v: &Value) -> Option<String> {
    v.as_str().map(String::from)
}

fn load(dir: &Path, prefix: &str, name: &str) -> Value {
    let path = dir.join(format!("{prefix}{name}-fixture.json"));
    let text = urbanstyle_geo::files::take(&path).unwrap_or_else(|e| panic!("cannot read {}: {e}", path.display()));
    serde_json::from_slice(&text).unwrap_or_else(|e| panic!("cannot parse {}: {e}", path.display()))
}

/// Where the tables are: SimReady's Parquet files and duckOSM's pass-0 folder. With them the blocks and the division read their inputs
/// from the tables (`urbanstyle-simready`) in place of the JSON fixtures.
pub struct Sources {
    pub simready: std::path::PathBuf,
    pub pass0: std::path::PathBuf,
    /// duckOSM's `features-<name>.parquet` files (`rust/tools/export_features_parquet.py` until duckOSM writes them): the buildings, the
    /// points and the car parks of the `element` step.
    pub features: Option<std::path::PathBuf>,
}

/// The inputs of the blocks step and of the division read from the tables. Only the street and the area come from them; the blocks and the
/// corridors of the division are filled by the chain.
fn from_tables(s: &Sources) -> Result<(urbanstyle_blocks::Input, urbanstyle_division::Input), String> {
    use urbanstyle_simready::{blocks, boundary, division, osm};
    let zone = urbanstyle_geo::utm::zone_of(boundary::mean_lon(&s.pass0.join("boundary_main.parquet"))?);
    let area = boundary::read(&s.pass0.join("boundary_main.parquet"), Some(zone))?;
    let edges = division::Edges::read(&s.pass0.join("edges_driving.parquet"))?;
    let driving = osm::driving_ways(&s.pass0.join("edges_driving.parquet"))?;
    let ways = osm::ways(&s.pass0.join("raw_ways.parquet"), zone)?;
    let bs = blocks::read(&s.simready, &edges, &area)?;
    let ds = division::read(&s.simready, &edges, &area)?;
    let blocks_in = urbanstyle_blocks::Input {
        area: area.clone(),
        face: bs.face,
        lanes: bs.lanes,
        junctions: bs.junctions,
        drives: bs.drives,
        streets: bs.streets,
        paths: osm::paths(&ways, &driving, &area),
    };
    let division_in = urbanstyle_division::Input {
        area,
        blocks: Mp::new(vec![]),
        corridors: Mp::new(vec![]),
        carriageways: ds.carriageways,
        lanes: ds.lanes,
        junctions: ds.junctions,
        islands: ds.islands,
        stops: ds.stops,
        moves: ds.moves,
        faces: ds.faces,
        crossing_ways: osm::crossing_ways(&ways, &driving, &blocks_in.area),
        crossing_nodes: osm::crossing_nodes(&s.pass0.join("raw_nodes.parquet"), zone)?,
    };
    Ok((blocks_in, division_in))
}

/// Run the chain on the fixture files `<dir>/<prefix><name>-fixture.json` (blocks, division, ground, paths, model, element, object,
/// check, surface). `with_checks` false skips the checks: the `check` table is empty. The uids are new ones (`new-1`, ...): a build that keeps them gives the registry of the last build to `assign`.
pub fn run(dir: &Path, prefix: &str, out_dir: Option<&Path>, with_checks: bool, sources: Option<&Sources>) -> Built {
    let mut timings: Vec<(String, f64)> = Vec::new();
    let mut t = urbanstyle_geo::timing::now_s();
    let mut lap = |name: &str, t: &mut f64| {
        let now = urbanstyle_geo::timing::now_s();
        timings.push((name.to_string(), now - *t));
        *t = now;
    };

    // ---- read the raw inputs
    let (bx, dx, gx, px, mx, ex, ox, cx, sx) = (
        load(dir, prefix, "blocks"),
        load(dir, prefix, "division"),
        load(dir, prefix, "ground"),
        load(dir, prefix, "paths"),
        load(dir, prefix, "model"),
        load(dir, prefix, "element"),
        load(dir, prefix, "object"),
        load(dir, prefix, "check"),
        load(dir, prefix, "surface"),
    );
    lap("read the JSON files", &mut t);
    let (blocks_in, mut division_in) = match sources {
        None => (read::blocks_in::input(&bx), read::division_in::input(&dx)),
        Some(s) => from_tables(s).unwrap_or_else(|e| panic!("cannot read the tables: {e}")),
    };
    let mut ground_in = read::ground_in::input(&gx);
    // (with the features: the kinds of OSM ground and the lines come from the tables; the street, the corridors, the structures and the
    // buildings are put in below, from the steps)
    if let Some((s, f)) = sources.and_then(|s| s.features.as_ref().map(|f| (s, f))) {
        use urbanstyle_simready::{boundary, features, ground};
        let zone = urbanstyle_geo::utm::zone_of(boundary::mean_lon(&s.pass0.join("boundary_main.parquet")).unwrap());
        let lots = features::lots(&f.join("features-sites.parquet"), zone).unwrap_or_else(|e| panic!("cannot read the features: {e}"));
        let g = ground::read(f, &s.pass0, zone, &lots).unwrap_or_else(|e| panic!("cannot read the ground inputs: {e}"));
        ground_in.order = g.order;
        ground_in.lines = g.lines;
        ground_in.has_parcels = false;
    }
    let area = division_in.area.clone();
    lap(if sources.is_some() { "read the tables" } else { "parse the inputs" }, &mut t);

    // ---- the blocks and the corridors
    let blocks = urbanstyle_blocks::build(&blocks_in);
    lap("blocks", &mut t);
    if std::env::var("URBANSTYLE_COUNTS").is_ok() { eprintln!("COUNT blocks {} corridors {}", blocks.blocks.len(), blocks.corridors.len()); }

    // ---- the division of the street space
    let blocks_u = ops::union_all(blocks.blocks.iter().map(|b| Mp::new(vec![b.polygon.clone()])).collect::<Vec<_>>().iter());
    let corridors_u = ops::union_all(blocks.corridors.iter().map(|c| &c.polygon));
    division_in.blocks = blocks_u.clone();
    division_in.corridors = corridors_u;
    let div = urbanstyle_division::build(&division_in);
    lap("division", &mut t);
    if std::env::var("URBANSTYLE_COUNTS").is_ok() { eprintln!("COUNT units {} (sub {}) parts {} turn_rows {} approach_rows {}", div.units.len(), div.units.iter().filter(|u| u.subsection).count(), div.units.iter().map(|u| u.parts.len()).sum::<usize>(), div.turn_rows.len(), div.approach_rows.len()); }

    // ---- the building and lot rows of `element` (the buildings are the ground's kind building)
    let ei = &ex["input"];
    let tags = |v: &Value| -> BTreeMap<String, String> { v.as_object().unwrap().iter().map(|(k, x)| (k.clone(), x.as_str().unwrap_or("").to_string())).collect() };
    let (buildings, pois, lots): (Vec<urbanstyle_model::elements::BuildingIn>, Vec<urbanstyle_model::elements::PoiIn>, Vec<urbanstyle_model::elements::LotIn>) =
        match sources.and_then(|s| s.features.as_ref().map(|f| (s, f))) {
            Some((s, f)) => {
                use urbanstyle_simready::{boundary, features};
                let zone = urbanstyle_geo::utm::zone_of(boundary::mean_lon(&s.pass0.join("boundary_main.parquet")).unwrap());
                let e = |e: String| -> ! { panic!("cannot read the features: {e}") };
                (
                    features::buildings(&f.join("features-buildings.parquet"), zone).unwrap_or_else(|x| e(x)),
                    features::pois(&f.join("features-pois.parquet"), zone).unwrap_or_else(|x| e(x)),
                    features::lots(&f.join("features-sites.parquet"), zone).unwrap_or_else(|x| e(x)),
                )
            }
            None => (
                ei["buildings"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|b| urbanstyle_model::elements::BuildingIn { osm_type: b["type"].as_str().unwrap().into(), osm_id: b["osm_id"].as_i64().unwrap(), name: os(&b["name"]), kind: os(&b["kind"]), tags: tags(&b["tags"]), geom: io::multi_polygon(&b["geom"]).unwrap() })
                    .collect(),
                ei["pois"].as_array().unwrap().iter().map(|p| urbanstyle_model::elements::PoiIn { tags: tags(&p["tags"]), point: Coord { x: p["point"][0].as_f64().unwrap(), y: p["point"][1].as_f64().unwrap() } }).collect(),
                ei["lots"].as_array().unwrap().iter().map(|l| urbanstyle_model::elements::LotIn { id: l["id"].as_str().unwrap().into(), typ: l["type"].as_str().unwrap().into(), name: os(&l["name"]), level: l["level"].as_i64().unwrap() as i32, geom: io::multi_polygon(&l["geom"]).unwrap() }).collect(),
            ),
        };
    let elements = urbanstyle_model::elements::build(&buildings, &pois, &lots);
    lap("elements", &mut t);

    // ---- the units of the division as the later steps read them (work.unit, work.part, work.mark, work.subsection)
    struct Un<'a> {
        u: &'a urbanstyle_division::Unit,
        geom: Mp,
    }
    // (as simready.py writes them: each part on a 1 cm grid, a part under 0.05 m2 left out, the space the union of its parts)
    let mut div = div;
    if std::env::var("URBANSTYLE_COUNTS").is_ok() {
        let raw: f64 = div.units.iter().flat_map(|u| u.parts.iter()).map(|p| ops::area(&p.geom)).sum();
        let snapped: f64 = div.units.iter().flat_map(|u| u.parts.iter()).map(|p| ops::area(&ops::snap(&p.geom, GRID_M))).sum();
        let opened: f64 = div.units.iter().flat_map(|u| u.parts.iter()).map(|p| ops::area(&ops::wide(&ops::snap(&p.geom, GRID_M), GRID_M))).sum();
        { let mut w: Vec<(f64, String)> = div.units.iter().flat_map(|u| u.parts.iter().map(move |p| (u, p))).map(|(u, p)| { let a = ops::area(&p.geom); let b = ops::area(&ops::snap(&p.geom, GRID_M)); (a - b, format!("{} {} raw {a:.1} snapped {b:.1} polys {} holes {}", u.id, p.typ, p.geom.0.len(), p.geom.0.iter().map(|q| q.interiors().len()).sum::<usize>())) }).collect(); w.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap()); for x in w.iter().take(5) { eprintln!("COUNT worst {}", x.1); } }
        eprintln!("COUNT part area: raw {raw:.0} snapped {snapped:.0} opened {opened:.0}");
    }
    for u in div.units.iter_mut() {
        for p in u.parts.iter_mut() {
            // (a part thinner than the grid collapses, as in `set_precision`)
            if std::env::var("URBANSTYLE_RAW").is_err() { p.geom = ops::wide(&ops::snap(&p.geom, GRID_M), GRID_M); }
        }
        u.parts.retain(|p| ops::area(&p.geom) > MIN_PART_M2);
    }
    let units: Vec<Un> = div.units.iter().map(|u| Un { u, geom: if std::env::var("URBANSTYLE_RAW").is_ok() { ops::union_all(u.parts.iter().map(|p| &p.geom)) } else { close(&ops::snap(&ops::union_all(u.parts.iter().map(|p| &p.geom)), GRID_M)) } }).collect();
    let cw: BTreeMap<i64, &urbanstyle_division::Carriageway> = division_in.carriageways.iter().map(|c| (c.id, c)).collect();

    // ---- the ground: the kinds take the ground in the order of ground.gather; the street, the paths and the structures come from the steps
    ground_in.land = Some(ops::intersection(&blocks_u, &area));
    for k in ground_in.order.iter_mut() {
        match (k.typ.as_str(), k.source.as_str()) {
            ("street", _) => k.items = units.iter().filter(|x| x.u.level == 0).map(|x| urbanstyle_ground::Item { r#ref: x.u.id.clone(), name: None, geom: x.geom.clone() }).collect(),
            ("path", "urbanstyle") => k.items = blocks.corridors.iter().map(|c| urbanstyle_ground::Item { r#ref: c.id.clone(), name: c.name.clone(), geom: c.polygon.clone() }).collect(),
            ("structure", "urbanstyle") => k.items = units.iter().filter(|x| x.u.level > 0).map(|x| urbanstyle_ground::Item { r#ref: x.u.id.clone(), name: None, geom: x.geom.clone() }).collect(),
            ("building", _) => {
                k.items = elements.iter().filter(|e| e.kind == "building" && e.level_min <= 0 && e.level_max >= 0).map(|e| urbanstyle_ground::Item { r#ref: e.id.clone(), name: e.name.clone(), geom: e.geom.clone() }).collect()
            }
            _ => {}
        }
    }
    if std::env::var("URBANSTYLE_COUNTS").is_ok() {
        let polys: usize = units.iter().filter(|x| x.u.level == 0).map(|x| x.geom.0.len()).sum();
        let multi = units.iter().filter(|x| x.u.level == 0 && x.geom.0.len() > 1).count();
        let area_sum: f64 = units.iter().filter(|x| x.u.level == 0).map(|x| ops::area(&x.geom)).sum();
        { let mut a: Vec<f64> = units.iter().filter(|x| x.u.level == 0).flat_map(|x| x.geom.0.iter().map(|p| geo::Area::unsigned_area(p))).collect(); a.sort_by(|x, y| x.partial_cmp(y).unwrap()); let n = |t: f64| a.iter().filter(|v| **v < t).count(); eprintln!("COUNT polygon areas: <0.01 {} <0.05 {} <0.5 {} <5 {} of {}", n(0.01), n(0.05), n(0.5), n(5.0), a.len()); }
        if let Ok(path) = std::env::var("URBANSTYLE_DUMP_UNITS") { let v: Vec<Value> = units.iter().filter(|x| x.u.level == 0).map(|x| serde_json::json!({"id": x.u.id, "geom": x.geom.0.iter().map(|p| std::iter::once(p.exterior()).chain(p.interiors()).map(|r| r.0.iter().map(|c| vec![c.x, c.y]).collect::<Vec<_>>()).collect::<Vec<_>>()).collect::<Vec<_>>()})).collect(); std::fs::write(path, serde_json::to_string(&v).unwrap()).unwrap(); }
        eprintln!("COUNT unit polygons {polys}, units in several parts {multi}, area {area_sum:.0}; land polygons {}", ground_in.land.as_ref().map_or(0, |l| l.0.len()));
    }
    let ground = urbanstyle_ground::build(&ground_in);
    lap("ground", &mut t);
    if std::env::var("URBANSTYLE_COUNTS").is_ok() { let mut by: BTreeMap<&str, usize> = BTreeMap::new(); for g in &ground { *by.entry(g.typ.as_str()).or_default() += 1; } eprintln!("COUNT ground {} {:?}", ground.len(), by); let mut sm: BTreeMap<&str, (usize, usize)> = BTreeMap::new(); for g in &ground { let a = geo::Area::unsigned_area(&g.geom); let e = sm.entry(g.typ.as_str()).or_default(); if a < 0.5 { e.0 += 1; } else if a < 5.0 { e.1 += 1; } } eprintln!("COUNT ground rows under 0.5 m2 / under 5 m2: {:?}", sm); let mut shown = 0; for g in ground.iter().filter(|g| g.typ == "street" && geo::Area::unsigned_area(&g.geom) < 0.5) { if shown >= 6 { break; } shown += 1; let a = geo::Area::unsigned_area(&g.geom); let per: f64 = std::iter::once(g.geom.exterior()).chain(g.geom.interiors()).map(|r| urbanstyle_geo::lines::length(r)).sum(); let r = geo::BoundingRect::bounding_rect(&g.geom).unwrap(); eprintln!("COUNT tiny {} area {a:.4} perimeter {per:.2} mean width {:.4} bbox {:.1} x {:.1}", g.id, 2.0 * a / per, r.width(), r.height()); } }

    // ---- layer 1, the surfaces
    let layer = |v: &Value| urbanstyle_ground::surfaces::Layer { items: v.as_array().unwrap().iter().map(|x| (x["ref"].as_str().unwrap().to_string(), io::multi_polygon(&x["geom"]).unwrap())).collect() };
    let sl = &sx["input"]["layers"];
    let osm_layers = sources.and_then(|s| s.features.as_ref().map(|f| (s, f))).map(|(s, f)| {
        let zone = urbanstyle_geo::utm::zone_of(urbanstyle_simready::boundary::mean_lon(&s.pass0.join("boundary_main.parquet")).unwrap());
        let l = urbanstyle_simready::features::surface_layers(f, zone).unwrap_or_else(|e| panic!("cannot read the surface layers: {e}"));
        let ways = urbanstyle_simready::osm::ways(&s.pass0.join("raw_ways.parquet"), zone).unwrap();
        let driving = urbanstyle_simready::osm::driving_ways(&s.pass0.join("edges_driving.parquet")).unwrap();
        let walks: Vec<(String, Vec<LineString<f64>>)> = urbanstyle_simready::osm::walking_ways(&ways, &driving).iter().map(|w| (format!("w{}", w.id), w.lines.clone())).collect();
        (l, walks)
    });
    let layers = urbanstyle_ground::surfaces::Layers {
        verge: osm_layers.as_ref().map_or_else(|| layer(&sl["verge"]), |o| urbanstyle_ground::surfaces::Layer { items: o.0.verge.clone() }),
        garden: osm_layers.as_ref().map_or_else(|| layer(&sl["garden"]), |o| urbanstyle_ground::surfaces::Layer { items: o.0.garden.clone() }),
        play: osm_layers.as_ref().map_or_else(|| layer(&sl["play"]), |o| urbanstyle_ground::surfaces::Layer { items: o.0.play.clone() }),
        buildings: urbanstyle_ground::surfaces::Layer { items: elements.iter().filter(|e| e.kind == "building" && e.level_min <= 0 && e.level_max >= 0).map(|e| (e.id.clone(), e.geom.clone())).collect() },
        lots: urbanstyle_ground::surfaces::Layer { items: elements.iter().filter(|e| e.kind == "lot").map(|e| (e.id.clone(), e.geom.clone())).collect() },
        sites: osm_layers.as_ref().map_or_else(|| layer(&sl["sites"]), |o| urbanstyle_ground::surfaces::Layer { items: o.0.sites.clone() }),
        walks: match &osm_layers {
            Some(o) => o.1.clone(),
            None => sl["walks"].as_array().unwrap().iter().map(|w| (w["ref"].as_str().unwrap().to_string(), w["lines"].as_array().unwrap().iter().map(|x| io::line_string(x).unwrap()).collect())).collect(),
        },
    };
    let surface_in = urbanstyle_ground::surfaces::SurfaceInput {
        ground: ground.iter().map(|g| urbanstyle_ground::surfaces::GroundItem { id: g.id.clone(), typ: g.typ.clone(), r#ref: g.r#ref.clone(), source: Some(g.source.clone()), method: Some(g.method.clone()), geom: Mp::new(vec![g.geom.clone()]) }).collect(),
        parts: units.iter().flat_map(|x| x.u.parts.iter().map(move |p| urbanstyle_ground::surfaces::StreetPart { unit: x.u.id.clone(), typ: p.typ.clone(), source: Some(p.source.clone()), geom: p.geom.clone() })).collect(),
        layers,
    };
    let surfaces = urbanstyle_ground::surfaces::build(&surface_in);
    lap("surfaces", &mut t);

    // ---- the paths
    let pi = &px["input"];
    let path_in = urbanstyle_paths::Input {
        level: 0,
        footway_w: pi["footway_w"].as_f64().unwrap(),
        items: ground.iter().filter(|g| g.typ == "path").map(|g| urbanstyle_paths::PathItem { id: g.id.clone(), r#ref: g.r#ref.clone().unwrap_or_default(), geom: Mp::new(vec![g.geom.clone()]) }).collect(),
        corridors: blocks.corridors.iter().map(|c| (c.id.clone(), urbanstyle_paths::Corridor { name: c.name.clone(), width: Some(c.width_m), source: Some(c.width_source.to_string()), method: Some(c.width_method.to_string()) })).collect(),
        lines: pi["lines"].as_array().unwrap().iter().map(|l| urbanstyle_paths::PathLine { way: l["way"].as_str().unwrap().into(), class: os(&l["class"]), name: os(&l["name"]), src: l["src"].as_i64(), dst: l["dst"].as_i64(), line: io::line_string(&l["line"]).unwrap() }).collect(),
    };
    let path_spaces = urbanstyle_paths::build(&path_in);
    lap("paths", &mut t);

    // ---- the model
    use urbanstyle_model as m;
    let mi = &mx["input"];
    // (the widths of the ways, the places of the junction nodes and the roundabouts: from duckOSM's files when the tables are given)
    let osm_model = sources.and_then(|s| s.features.as_ref().map(|_| s)).map(|s| {
        use urbanstyle_simready::{boundary, osm};
        let zone = urbanstyle_geo::utm::zone_of(boundary::mean_lon(&s.pass0.join("boundary_main.parquet")).unwrap());
        let ways = osm::ways(&s.pass0.join("raw_ways.parquet"), zone).unwrap();
        let edges = osm::driving_edges(&s.pass0.join("edges_driving.parquet"), zone).unwrap();
        (osm::way_widths(&ways), osm::node_points(&edges), osm::roundabouts(&edges, &ways, &area), urbanstyle_simready::streets::read(&edges, &ways))
    });
    let model_in = m::Input {
        units: units.iter().map(|x| m::Unit { id: x.u.id.clone(), kind: if x.u.subsection { "subsection" } else { "intersection" }.into(), level: x.u.level, geom: x.geom.clone() }).collect(),
        subsections: units
            .iter()
            .filter(|x| x.u.subsection)
            .map(|x| {
                let c = cw[&x.u.cws[0]];
                let width: f64 = x.u.parts.iter().filter(|p| p.lane.is_some()).map(|p| p.width_m.unwrap_or(0.0)).sum();
                m::Subsection {
                    id: x.u.id.clone(),
                    section: x.u.section.clone().unwrap_or_default(),
                    level: x.u.level,
                    line: x.u.axis.clone(),
                    width: Some((width * 100.0).round() / 100.0),
                    oneway: Some(c.oneway && x.u.cws.len() == 1),
                    length: x.u.axis.as_ref().map(|a| (urbanstyle_geo::lines::length(a) * 10.0).round() / 10.0),
                    left_extra: None,
                    class: Some(c.highway.clone()),
                }
            })
            .collect(),
        parts: units
            .iter()
            .flat_map(|x| {
                x.u.parts.iter().enumerate().map(move |(n, p)| m::Part {
                    id: format!("{}#{}", x.u.id, n + 1),
                    unit: x.u.id.clone(),
                    typ: p.typ.clone(),
                    direction: p.direction.clone(),
                    lane: p.lane,
                    road: p.road.clone(),
                    r#ref: Some(p.reference.clone()),
                    extra: m::PartExtra { lane_id: p.lane_id.clone(), width_m: p.width_m, width_source: Some(p.width_source.clone()), width_method: p.width_method.clone(), source: Some(p.source.clone()), method: Some(p.method.clone()), road_class: p.road_class.clone(), oneway: p.oneway.clone() },
                    geom: p.geom.clone(),
                })
            })
            .collect(),
        marks: units.iter().flat_map(|x| x.u.marks.iter().map(move |k| m::Mark { unit: x.u.id.clone(), typ: k.typ.clone(), level: x.u.level, source: Some(k.source.clone()), method: k.method.clone(), reference: k.reference.clone(), lines: vec![k.line.clone()] })).collect(),
        ground: ground.iter().map(|g| m::GroundIn { id: g.id.clone(), typ: g.typ.clone(), level: 0, name: g.name.clone(), source: Some(g.source.clone()), method: Some(g.method.clone()), r#ref: g.r#ref.clone(), geom: Mp::new(vec![g.geom.clone()]) }).collect(),
        blocks: blocks.blocks.iter().map(|b| m::BlockIn { id: b.id.clone(), level: 0, source: None, method: None, geom: Mp::new(vec![b.polygon.clone()]) }).collect(),
        block_sides: blocks.blocks.iter().flat_map(|b| b.sides.iter().map(move |s| m::BlockSideIn { block: b.id.clone(), way: s.way, name: s.name.clone(), class: Some(s.class.clone()), distance_m: Some(s.distance_m), basis: None, method: None })).collect(),
        corridors: blocks.corridors.iter().map(|c| m::CorridorIn { id: c.id.clone(), name: c.name.clone(), width: Some(c.width_m), source: Some(c.width_source.to_string()), method: Some(c.width_method.to_string()) }).collect(),
        surfaces: surfaces.iter().map(|s| m::SurfaceIn { id: s.id.clone(), ground: s.ground.clone() }).collect(),
        owidth: match &osm_model { Some(o) => o.0.clone().into_iter().collect(), None => mi["owidth"].as_object().unwrap().iter().map(|(k, v)| (k.clone(), v.as_f64().unwrap())).collect() },
        junctions: div.junction_rows.iter().map(|(i, n, lv)| m::JunctionIn { intersection: i.clone(), node: *n, level: *lv, cluster: Some(i.clone()) }).collect(),
        node_pt: match &osm_model { Some(o) => o.1.clone().into_iter().collect(), None => mi["node_pt"].as_object().unwrap().iter().map(|(k, v)| (k.parse().unwrap(), Coord { x: v[0].as_f64().unwrap(), y: v[1].as_f64().unwrap() })).collect() },
        way_street: match &osm_model { Some(o) => o.3.way_street.clone(), None => mi["way_street"].as_array().unwrap().iter().filter_map(|w| Some((format!("w{}", w["osm_id"]), w["street"].as_str()?.to_string()))).collect() },
        name_street: match &osm_model { Some(o) => o.3.name_street.clone(), None => mi["name_street"].as_array().unwrap().iter().filter_map(|w| Some(((w["name"].as_str()?.to_string(), w["level"].as_i64()? as i32), w["street"].as_str()?.to_string()))).collect() },
        roundabouts: match &osm_model { Some(o) => o.2.clone(), None => mi["roundabouts"].as_array().unwrap().iter().map(|l| io::line_string(l).unwrap()).collect() },
        path_spaces: path_spaces
            .iter()
            .map(|p| m::PathSpaceIn {
                id: p.id.clone(),
                kind: if p.kind == urbanstyle_paths::Kind::Intersection { "path intersection" } else { "path section" }.into(),
                ground: p.ground.clone(),
                level: 0,
                name: p.name.clone(),
                class: p.class.clone(),
                ways: p.ways.clone(),
                nodes: p.nodes.clone(),
                width: Some(p.width_m),
                width_source: p.width_source.clone(),
                width_method: p.width_method.clone(),
                length: p.length,
                pred: p.links.clone(),
                succ: p.links.clone(),
                axis: p.axis.clone(),
                geom: p.geom.clone(),
            })
            .collect(),
        close_gaps_m: GRID_M,
        turns: div.turn_rows.iter().map(|t| m::TurnIn { unit: t.unit.clone(), level: t.level, from_edge: Some(t.from_edge.clone()), from_lane: t.from_lane, to_edge: Some(t.to_edge.clone()), to_lane: t.to_lane, turn: t.turn.clone(), source: Some("simready".into()), vehicles: Some(t.vehicles.clone()), condition: None, lines: t.lines.clone() }).collect(),
        approaches: div.approach_rows.iter().map(|a| m::ApproachIn { unit: a.unit.clone(), level: a.level, from_edge: Some(a.from_edge.clone()), lane: a.lane, moves: Some(a.moves), ways: Some(a.ways.clone()), arrow: Some(a.arrow), no_arrow_because: a.no_arrow_because.clone() }).collect(),
    };
    let model = m::build(&model_in);
    lap("model", &mut t);

    // ---- the street objects, in the spaces and parts of the model
    let nodes: Vec<m::objects::NodeIn> = match sources {
        Some(s) if s.features.is_some() => {
            let zone = urbanstyle_geo::utm::zone_of(urbanstyle_simready::boundary::mean_lon(&s.pass0.join("boundary_main.parquet")).unwrap());
            urbanstyle_simready::osm::object_nodes(&s.pass0.join("raw_nodes.parquet"), zone).unwrap_or_else(|e| panic!("cannot read the nodes: {e}"))
        }
        _ => ox["input"]["nodes"]
            .as_array()
            .unwrap()
            .iter()
            .map(|n| m::objects::NodeIn { id: n["id"].as_i64().unwrap(), tags: tags(&n["tags"]), xy: Coord { x: n["xy"][0].as_f64().unwrap(), y: n["xy"][1].as_f64().unwrap() } })
            .collect(),
    };
    let space_refs: Vec<m::objects::SpaceRef> = model.spaces.iter().filter(|s| matches!(s.kind.as_str(), "subsection" | "sub-intersection" | "ring sector" | "centre")).map(|s| m::objects::SpaceRef { id: &s.id, level: s.level, geom: &s.geom }).collect();
    let part_refs: Vec<m::objects::PartRef> = model.parts.iter().map(|p| m::objects::PartRef { id: &p.id, space: &p.space, geom: &p.geom }).collect();
    let objects = m::objects::build(&nodes, &space_refs, &part_refs, urbanstyle_model::elements::LEVELS.0, urbanstyle_model::elements::LEVELS.1);
    drop((space_refs, part_refs));
    lap("objects", &mut t);

    // ---- the checks (a product build skips them)
    let checks: Vec<urbanstyle_checks::Check> = if with_checks {
    use urbanstyle_checks as c;
    let ci = &cx["input"];
    let unit_level: BTreeMap<&str, i32> = units.iter().map(|x| (x.u.id.as_str(), x.u.level)).collect();
    let check_in = c::Input {
        area: area.clone(),
        units: units.iter().map(|x| c::Unit { id: x.u.id.clone(), kind: if x.u.subsection { "subsection" } else { "intersection" }.into(), level: x.u.level, geom: x.geom.clone() }).collect(),
        parts: model_in.parts.iter().map(|p| {
            let src = units.iter().find(|x| x.u.id == p.unit);
            let dp = src.and_then(|x| x.u.parts.iter().find(|q| q.reference == p.r#ref.clone().unwrap_or_default() && q.typ == p.typ && q.lane == p.lane));
            c::PartIn { unit: p.unit.clone(), id: p.id.clone(), level: unit_level.get(p.unit.as_str()).copied().unwrap_or(0), typ: p.typ.clone(), width_method: dp.and_then(|q| q.width_method.clone()), source: dp.map(|q| q.source.clone()), width: dp.and_then(|q| q.width_m), geom: p.geom.clone() }
        }).collect(),
        ground: ground.iter().map(|g| c::GroundIn { id: g.id.clone(), level: 0, typ: g.typ.clone(), geom: Mp::new(vec![g.geom.clone()]) }).collect(),
        surfaces: surfaces.iter().map(|s| c::SurfaceIn { id: s.id.clone(), ground: s.ground.clone(), geom: Mp::new(vec![s.geom.clone()]) }).collect(),
        blocks: blocks.blocks.iter().map(|b| c::BlockIn { id: b.id.clone(), geom: Mp::new(vec![b.polygon.clone()]) }).collect(),
        buildings: elements.iter().filter(|e| e.kind == "building" && e.level_min <= 0 && e.level_max >= 0).map(|e| e.geom.clone()).collect(),
        node_pt: model_in.node_pt.clone(),
        junctions: model_in.junctions.iter().map(|j| c::JunctionIn { intersection: j.intersection.clone(), level: j.level, node: j.node }).collect(),
        subsections: model_in.subsections.iter().map(|s| c::SubsectionIn { id: s.id.clone(), level: s.level, line: s.line.clone(), width: s.width }).collect(),
        approaches: model_in.approaches.iter().map(|a| c::ApproachIn { unit: a.unit.clone(), from_edge: a.from_edge.clone(), moves: a.moves, ways: a.ways.clone(), arrow: a.arrow, no_arrow_because: a.no_arrow_because.clone() }).collect(),
        guides: units.iter().map(|x| (x.u.level, x.u.marks.iter().filter(|k| k.typ == "guide line").map(|k| k.line.clone()).collect::<Vec<LineString<f64>>>())).filter(|(_, v)| !v.is_empty()).flat_map(|(lv, v)| v.into_iter().map(move |l| (lv, vec![l]))).collect(),
        roads: ci["roads"].as_array().unwrap().iter().map(|r| c::RoadIn { osm_id: r["osm_id"].as_i64().unwrap(), src: r["src"].as_i64(), dst: r["dst"].as_i64(), level: r["level"].as_i64().unwrap() as i32, typ: r["type"].as_str().unwrap().into(), street: r["street"].as_bool().unwrap(), line: (!r["line"].is_null()).then(|| io::line_string(&r["line"]).unwrap()), class: os(&r["class"]), width: r["width"].as_f64(), subtype: os(&r["subtype"]) }).collect(),
        marks: units.iter().flat_map(|x| x.u.marks.iter().filter(|k| matches!(k.typ.as_str(), "kerb" | "centre line" | "lane line")).map(move |k| c::MarkIn { unit: x.u.id.clone(), typ: k.typ.clone(), source: Some(k.source.clone()), lines: vec![k.line.clone()] })).collect(),
        sections: model_in.subsections.iter().map(|s| (s.id.clone(), s.section.clone())).collect(),
        shared_m: GRID_M / 2.0,
    };
    let mut checks = c::partitions(&check_in);
    checks.extend(c::roadway::roadway(&check_in));
    checks.extend(c::roadway::joints(&check_in));
    checks.push(c::roadway::lane_joints(&check_in));
    checks.extend(c::rules::rules(&check_in));
    lap("checks", &mut t);
    checks
    } else {
        Vec::new()
    };

    // ---- the registry: the profile of every thing and its uid (new ones: the first build)
    let area_name = mx["input"].get("area_name").and_then(|v| v.as_str()).map(String::from);
    let things = m::registry::profiles(&model, area_name.as_deref(), &objects, &elements);
    let mut n = 0u64;
    let (registry, uids) = m::registry::assign(&[], &things, "built", &mut || {
        n += 1;
        format!("u{n:08}")
    });
    lap("registry", &mut t);

    // ---- the tables of the page, as Parquet files
    let tables = urbanstyle_tables::all_tables(&urbanstyle_tables::model_tables::Parts {
        model: &model,
        elements: &elements,
        objects: &objects,
        surfaces: &surfaces,
        checks: &checks,
        registry: &registry,
        uids: &uids,
        area_name: None,
        area: &area,
        zone: 32,
        built: "built",
    });
    let mut bytes = 0usize;
    if let Some(d) = out_dir {
        std::fs::create_dir_all(d).expect("the output folder");
        for tb in &tables {
            bytes += tb.write(d).expect("a Parquet file");
        }
    } else {
        bytes = tables.iter().map(|tb| tb.parquet().len()).sum();
    }
    lap(&format!("tables ({} files, {:.1} MB)", tables.len(), bytes as f64 / 1e6), &mut t);

    Built { model, elements, objects, surfaces, checks, things, registry, uids, timings }
}
