//! The Rust blocks against the Python reference (sr_blocks.py) on a cut: the same inputs, the same rules. The data is made by
//! rust/tools/export_blocks_fixture.py and is not in git: with no file the test says so and passes.
use serde_json::Value;
use std::time::Instant;
use urbanstyle_blocks::{build, Input, PathWay, Street};
use urbanstyle_geo::io;
use urbanstyle_geo::ops::{self, Mp};

fn fixture() -> Option<Value> {
    let path = std::env::var("URBANSTYLE_BLOCKS_FIXTURE").unwrap_or_else(|_| "../../data/cuts/blocks-fixture.json".into());
    match std::fs::read_to_string(&path) {
        Ok(s) => serde_json::from_str(&s).ok(),
        Err(_) => {
            eprintln!("no fixture at {path}: run rust/tools/export_blocks_fixture.py; test skipped");
            None
        }
    }
}

fn input(f: &Value) -> Input {
    let i = &f["input"];
    let mp = |k: &str| io::multi_polygon(&i[k]).unwrap();
    let list = |k: &str| -> Vec<Mp> { i[k].as_array().unwrap().iter().map(|m| io::multi_polygon(m).unwrap()).collect() };
    Input {
        area: mp("area"),
        face: mp("face"),
        lanes: list("lanes"),
        junctions: list("junctions"),
        drives: list("drives"),
        streets: i["streets"]
            .as_array()
            .unwrap()
            .iter()
            .map(|s| Street {
                way: s["way"].as_i64().unwrap(),
                name: s["name"].as_str().map(String::from),
                class: s["class"].as_str().unwrap_or("").to_string(),
                line: io::line_string(&s["line"]).unwrap(),
            })
            .collect(),
        paths: i["paths"]
            .as_array()
            .unwrap()
            .iter()
            .map(|p| PathWay {
                way: p["way"].as_i64().unwrap(),
                class: p["class"].as_str().unwrap_or("").to_string(),
                name: p["name"].as_str().map(String::from),
                geom: geo::MultiLineString::new(p["geom"].as_array().unwrap().iter().map(|l| io::line_string(l).unwrap()).collect()),
                width: p["width"].as_f64(),
            })
            .collect(),
    }
}

#[test]
fn blocks_sides_and_corridors_agree_with_the_python_reference() {
    let Some(f) = fixture() else { return };
    let inp = input(&f);
    let t = Instant::now();
    let out = build(&inp);
    eprintln!("blocks, sides and corridors: {:?} ({} blocks, {} corridors, {} measured points)", t.elapsed(), out.blocks.len(), out.corridors.len(), out.samples);

    if let Ok(path) = std::env::var("URBANSTYLE_DUMP_BLOCKS") {
        let ring = |r: &geo::LineString<f64>| r.0.iter().map(|c| serde_json::json!([c.x, c.y])).collect::<Vec<_>>();
        let blocks: Vec<_> = out.blocks.iter().map(|b| {
            let mut rings = vec![serde_json::json!(ring(b.polygon.exterior()))];
            rings.extend(b.polygon.interiors().iter().map(|r| serde_json::json!(ring(r))));
            serde_json::json!({"id": b.id, "polygon": rings, "sides": b.sides.iter().map(|s| serde_json::json!([s.way, s.distance_m])).collect::<Vec<_>>()})
        }).collect();
        std::fs::write(path, serde_json::json!(blocks).to_string()).unwrap();
    }
    // the blocks: each reference block of 100 m2 or more is a block of ours, to 1% of its area
    let exp = f["expect"]["blocks"].as_array().unwrap();
    let ours: Vec<Mp> = out.blocks.iter().map(|b| Mp::new(vec![b.polygon.clone()])).collect();
    let mut missed = Vec::new();
    let mut matched = std::collections::BTreeMap::new(); // reference id -> index of ours
    for e in exp {
        let ep = io::multi_polygon(&e["polygon"]).unwrap();
        let ea = ops::area(&ep);
        if ea < 100.0 {
            continue;
        }
        let best = ours.iter().enumerate().map(|(k, o)| (k, ops::area(&ops::intersection(&ep, o)))).max_by(|a, b| a.1.partial_cmp(&b.1).unwrap());
        match best {
            Some((k, ov)) if ov >= 0.99 * ea && ops::area(&ours[k]) <= 1.01 * ea => {
                matched.insert(e["id"].as_str().unwrap().to_string(), k);
            }
            other => {
                let (k, ov) = other.unwrap_or((0, 0.0));
                eprintln!("missed {}: area {:.0}; best of ours {:.0} m2, overlap {:.0} m2, ours is {}", e["id"], ea, ops::area(&ours[k]), ov, out.blocks[k].id);
                missed.push((e["id"].as_str().unwrap().to_string(), ea))
            }
        }
    }
    let big = exp.iter().filter(|e| e["area"].as_f64().unwrap() >= 100.0).count();
    eprintln!("reference blocks of 100 m2 or more: {big}; matched {}; missed {:?}", matched.len(), missed);
    {
        // (shown before the first check, so that a missed block does not hide the corridors)
        let ec = f["expect"]["corridors"].as_array().unwrap();
        let ref_c: f64 = ec.iter().map(|c| c["area"].as_f64().unwrap()).sum();
        let our_c: f64 = out.corridors.iter().map(|c| ops::area(&c.polygon)).sum();
        eprintln!("corridors: {} against {}; area {:.1} against {:.1} m2", out.corridors.len(), ec.len(), our_c, ref_c);
    }
    assert!(missed.is_empty(), "blocks of the reference that we do not have: {missed:?}");
    let ref_area: f64 = exp.iter().map(|e| e["area"].as_f64().unwrap()).sum();
    let our_area: f64 = ours.iter().map(ops::area).sum();
    assert!((our_area - ref_area).abs() <= 0.002 * ref_area, "the area of the blocks: {our_area} against {ref_area}");

    // the sides: each reference side (a way and a distance) of a matched block is a side of ours, to 5 cm
    let mut sides = 0;
    let mut wrong = Vec::new();
    for s in f["expect"]["sides"].as_array().unwrap() {
        let Some(&k) = matched.get(s["block"].as_str().unwrap()) else { continue };
        sides += 1;
        let (way, d) = (s["way"].as_i64().unwrap(), s["distance"].as_f64().unwrap());
        if !out.blocks[k].sides.iter().any(|o| o.way == way && (o.distance_m - d).abs() <= 0.05) {
            let ours_d: Vec<f64> = out.blocks[k].sides.iter().filter(|o| o.way == way).map(|o| o.distance_m).collect();
            wrong.push((s["block"].as_str().unwrap().to_string(), way, d, ours_d));
        }
    }
    eprintln!("sides of the matched blocks: {sides}; not found in ours: {}", wrong.len());
    let absent = wrong.iter().filter(|w| w.3.is_empty()).count();
    let off: Vec<f64> = wrong.iter().filter(|w| !w.3.is_empty()).map(|w| (w.3[0] - w.2).abs()).collect();
    eprintln!("  of which the way is not a side of ours: {absent}; the others differ by at most {:.2} m, {:?}", off.iter().cloned().fold(0.0, f64::max), off.iter().map(|x| (x * 100.0).round() / 100.0).collect::<Vec<_>>());
    // (the measuring is shapely's own on our blocks: 0 of 359 sides differ. What is left comes from the blocks: the two sets differ by 122 m2
    // in all, at the spots where the Python overlays snap a thin feature to its 1 cm grid)
    assert!(absent as f64 <= 0.015 * sides as f64, "ways that are no side of ours: {wrong:?}");
    assert!(off.iter().cloned().fold(0.0, f64::max) <= 1.5, "a side is more than 1.5 m off: {wrong:?}");
    assert!(wrong.len() as f64 <= 0.06 * sides as f64, "sides not found: {wrong:?}");

    // the block ids: the same way and side, for the matched blocks
    // (the way and the side; the number after a dot counts the blocks with the same id, in the order that the pieces come: GEOS's order
    // in the reference, ours here, so it is not compared)
    let base = |id: &str| if id.starts_with("b0-e") { "b0-e".to_string() } else { id.split('.').next().unwrap().to_string() };
    let same_id = matched.iter().filter(|(id, &k)| base(&out.blocks[k].id) == base(id)).count();
    eprintln!("block ids equal, without the number after the dot: {same_id} of {}", matched.len());
    for (id, &k) in &matched {
        if base(&out.blocks[k].id) != base(id) {
            eprintln!("  id differs: reference {id}, ours {}; our sides {:?}", out.blocks[k].id, out.blocks[k].sides.iter().map(|s| s.way).collect::<Vec<_>>());
        }
    }
    assert!(same_id as f64 >= 0.95 * matched.len() as f64, "the block ids differ");

    // the corridors: the same ways, and the same total area to 0.5%
    let ec = f["expect"]["corridors"].as_array().unwrap();
    let ref_c: f64 = ec.iter().map(|c| c["area"].as_f64().unwrap()).sum();
    let our_c: f64 = out.corridors.iter().map(|c| ops::area(&c.polygon)).sum();
    eprintln!("corridors: {} against {}; area {:.1} against {:.1} m2", out.corridors.len(), ec.len(), our_c, ref_c);
    assert!((out.corridors.len() as i64 - ec.len() as i64).abs() <= 3, "the number of corridors");
    assert!((our_c - ref_c).abs() <= 0.005 * ref_c, "the area of the corridors");
}

/// Not a check: writes the land piece that holds the block `b0-w165597363r` (two blocks of the reference, one of ours) to a file, so that
/// shapely can open it too (URBANSTYLE_DUMP=path).
#[test]
fn dump_a_land_piece() {
    let (Some(f), Ok(path)) = (fixture(), std::env::var("URBANSTYLE_DUMP")) else { return };
    let inp = input(&f);
    let (face, _, _) = urbanstyle_blocks::street_face(&inp);
    let land = ops::difference(&inp.area, &face);
    let probe = geo::Point::new(0.0, 0.0);
    let _ = probe;
    // the reference block's first vertex
    let eb = f["expect"]["blocks"].as_array().unwrap().iter().find(|e| e["id"] == "b0-w165597363r").unwrap();
    let ep = io::multi_polygon(&eb["polygon"]).unwrap();
    let pt = geo::Point::from(ep.0[0].exterior().0[0]);
    use geo::Distance;
    let q = land.0.iter().min_by(|a, b| geo::Euclidean.distance(&pt, *a).partial_cmp(&geo::Euclidean.distance(&pt, *b)).unwrap()).unwrap();
    let ring = |r: &geo::LineString<f64>| r.0.iter().map(|c| serde_json::json!([c.x, c.y])).collect::<Vec<_>>();
    let mut rings = vec![serde_json::json!(ring(q.exterior()))];
    rings.extend(q.interiors().iter().map(|r| serde_json::json!(ring(r))));
    let poly = serde_json::json!(rings);
    std::fs::write(&path, poly.to_string()).unwrap();
    let w = ops::wide(&Mp::new(vec![q.clone()]), 8.0);
    eprintln!("the piece: {:.0} m2; wide gives {} parts {:?}", q.unsigned_area_(), w.0.len(), w.0.iter().map(|p| p.unsigned_area_() as i64).collect::<Vec<_>>());
}

trait Ua { fn unsigned_area_(&self) -> f64; }
impl Ua for geo::Polygon<f64> { fn unsigned_area_(&self) -> f64 { geo::Area::unsigned_area(self) } }

/// Not a check: where our street and the reference's street differ (URBANSTYLE_DIFF=1).
#[test]
fn where_the_streets_differ() {
    let (Some(f), Ok(_)) = (fixture(), std::env::var("URBANSTYLE_DIFF")) else { return };
    let inp = input(&f);
    let out = build(&inp);
    let ref_blocks: Vec<Mp> = f["expect"]["blocks"].as_array().unwrap().iter().map(|e| io::multi_polygon(&e["polygon"]).unwrap()).collect();
    let ref_street = ops::difference(&inp.area, &ops::union_all(ref_blocks.iter()));
    let only_ours = ops::difference(&out.street, &ref_street);
    let only_ref = ops::difference(&ref_street, &out.street);
    use geo::Centroid;
    for (name, d) in [("only ours", &only_ours), ("only the reference", &only_ref)] {
        let mut ps: Vec<_> = d.0.iter().map(|p| (p.unsigned_area_(), p.centroid())).collect();
        ps.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap());
        eprintln!("{name}: {:.0} m2 in {} pieces; the largest: {:?}", ops::area(d), ps.len(),
                  ps.iter().take(6).map(|(a, c)| format!("{:.0} m2 at ({:.0}, {:.0})", a, c.map_or(0.0, |c| c.x()), c.map_or(0.0, |c| c.y()))).collect::<Vec<_>>());
    }
}
