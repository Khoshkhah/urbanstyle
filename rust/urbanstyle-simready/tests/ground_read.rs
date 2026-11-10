//! The ground input read from the features and duckOSM's files against the ground fixture (rust/tools/export_ground_fixture.py).
use serde_json::Value;
use std::path::PathBuf;
use urbanstyle_geo::{io, ops};
use urbanstyle_simready::{features, ground};

fn env(k: &str, d: &str) -> PathBuf {
    PathBuf::from(std::env::var(k).unwrap_or_else(|_| d.into()))
}

#[test]
fn ground_input_from_parquet() {
    let (fx, dir, pass0) = (
        env("URBANSTYLE_GROUND_FIXTURE", "../../data/cuts/monaco-ground-fixture.json"),
        env("URBANSTYLE_FEATURES_DIR", "../../data/cuts/features-monaco"),
        env("URBANSTYLE_PASS0_DIR", "../../../simready/build/monaco/pass0-rust"),
    );
    let Ok(text) = std::fs::read_to_string(&fx) else {
        eprintln!("no fixture at {}: test skipped", fx.display());
        return;
    };
    if !dir.join("features-land.parquet").exists() || !pass0.join("raw_ways.parquet").exists() {
        eprintln!("no features or duckOSM files: test skipped");
        return;
    }
    let f: Value = serde_json::from_str(&text).unwrap();
    let lots = features::lots(&dir.join("features-sites.parquet"), 32).unwrap();
    let t = std::time::Instant::now();
    let g = ground::read(&dir, &pass0, 32, &lots).unwrap();
    eprintln!("read in {:.2} s", t.elapsed().as_secs_f64());
    let order = f["input"]["order"].as_array().unwrap();
    assert_eq!(g.order.len(), order.len());
    for (k, theirs) in g.order.iter().zip(order) {
        assert_eq!((k.typ.as_str(), k.source.as_str(), k.method.as_str()), (theirs["type"].as_str().unwrap(), theirs["source"].as_str().unwrap(), theirs["method"].as_str().unwrap()));
        let items = theirs["items"].as_array().unwrap();
        // (the street, the corridors, the buildings and the structures of the streets come from the steps before)
        if k.items.is_empty() && !items.is_empty() {
            eprintln!("{:18} {} items there, none read (from the steps)", k.typ, items.len());
            continue;
        }
        let (a, b): (f64, f64) = (k.items.iter().map(|i| ops::area(&i.geom)).sum(), items.iter().map(|i| ops::area(&io::multi_polygon(&i["geom"]).unwrap())).sum());
        eprintln!("{:18} {} / {} items, {a:.1} / {b:.1} m2", k.typ, k.items.len(), items.len());
        assert_eq!(k.items.len(), items.len(), "{}", k.typ);
        // (the driveways are buffers of lines with round joins: `geo` approximates the arcs more coarsely than shapely, 0.9% more area)
        let limit = if k.typ == "alley" { 0.015 } else { 1e-3 };
        assert!((a - b).abs() <= limit * b.max(1.0), "{}: {a} against {b}", k.typ);
    }
    // the lines: the roads are the driving edges, the same ones; the walking ways are whole ways here, but the Python has duckOSM's walking edges
    // (cut at every junction node, and the virtual ones through the pedestrian areas)
    let lines = f["input"]["lines"].as_array().unwrap();
    let count = |ls: &[&str], t: &str| ls.iter().filter(|x| **x == t).count();
    let (mine, theirs): (Vec<&str>, Vec<&str>) = (g.lines.iter().map(|l| l.typ.as_str()).collect(), lines.iter().map(|l| l["type"].as_str().unwrap()).collect());
    eprintln!("roads {} / {}, walking ways {} / {} (walkway {} and cycleway {} there, as edges)", count(&mine, "road"), count(&theirs, "road"), count(&mine, "walkway"), lines.len() - count(&theirs, "road"), count(&theirs, "walkway"), count(&theirs, "cycleway"));
    assert!((count(&mine, "road") as f64 - count(&theirs, "road") as f64).abs() <= 0.05 * count(&theirs, "road") as f64);
}
