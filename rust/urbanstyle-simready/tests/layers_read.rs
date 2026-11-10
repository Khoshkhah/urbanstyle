//! The surface layers and the object nodes read from Parquet against the surface and object fixtures.
use serde_json::Value;
use std::path::PathBuf;
use urbanstyle_geo::{io, ops};
use urbanstyle_simready::{features, osm};

fn env(k: &str, d: &str) -> PathBuf {
    PathBuf::from(std::env::var(k).unwrap_or_else(|_| d.into()))
}

#[test]
fn layers_and_object_nodes_from_parquet() {
    let (sfx, ofx, dir, pass0) = (
        env("URBANSTYLE_SURFACE_FIXTURE", "../../data/cuts/monaco-surface-fixture.json"),
        env("URBANSTYLE_OBJECT_FIXTURE", "../../data/cuts/monaco-object-fixture.json"),
        env("URBANSTYLE_FEATURES_DIR", "../../data/cuts/features-monaco"),
        env("URBANSTYLE_PASS0_DIR", "../../../simready/build/monaco/pass0-rust"),
    );
    let (Ok(s), Ok(o)) = (std::fs::read_to_string(&sfx), std::fs::read_to_string(&ofx)) else {
        eprintln!("no fixtures: test skipped");
        return;
    };
    if !dir.join("features-land.parquet").exists() || !pass0.join("raw_nodes.parquet").exists() {
        eprintln!("no files: test skipped");
        return;
    }
    let (s, o): (Value, Value) = (serde_json::from_str(&s).unwrap(), serde_json::from_str(&o).unwrap());
    let l = features::surface_layers(&dir, 32).unwrap();
    let sl = &s["input"]["layers"];
    for (name, mine) in [("verge", &l.verge), ("garden", &l.garden), ("play", &l.play), ("sites", &l.sites)] {
        let theirs = sl[name].as_array().unwrap();
        let (a, b): (f64, f64) = (mine.iter().map(|x| ops::area(&x.1)).sum(), theirs.iter().map(|x| ops::area(&io::multi_polygon(&x["geom"]).unwrap())).sum());
        eprintln!("{name}: {} / {} items, {a:.1} / {b:.1} m2", mine.len(), theirs.len());
        assert_eq!(mine.len(), theirs.len(), "{name}");
        assert!((a - b).abs() <= 1e-3 * b.max(1.0));
    }
    let nodes = osm::object_nodes(&pass0.join("raw_nodes.parquet"), 32).unwrap();
    let theirs = o["input"]["nodes"].as_array().unwrap();
    eprintln!("object nodes {} / {}", nodes.len(), theirs.len());
    assert_eq!(nodes.len(), theirs.len());
    let by_id: std::collections::BTreeMap<i64, &Value> = theirs.iter().map(|n| (n["id"].as_i64().unwrap(), n)).collect();
    for n in &nodes {
        let t = by_id[&n.id];
        assert_eq!(n.tags.len(), t["tags"].as_object().unwrap().len(), "node {}", n.id);
        assert!((n.xy.x - t["xy"][0].as_f64().unwrap()).hypot(n.xy.y - t["xy"][1].as_f64().unwrap()) < 1e-3);
    }
}
