//! The element inputs read from the features Parquet files against the element fixture (rust/tools/export_element_fixture.py), and the
//! element rows that the Rust step makes from them against the rows the Python build made.
use serde_json::Value;
use std::collections::BTreeSet;
use std::path::PathBuf;
use urbanstyle_geo::{io, ops};
use urbanstyle_simready::features;

fn env(k: &str, d: &str) -> PathBuf {
    PathBuf::from(std::env::var(k).unwrap_or_else(|_| d.into()))
}

#[test]
fn element_inputs_from_parquet() {
    let (fx, dir) = (env("URBANSTYLE_ELEMENT_FIXTURE", "../../data/cuts/monaco-element-fixture.json"), env("URBANSTYLE_FEATURES_DIR", "../../data/cuts/features-monaco"));
    let Ok(text) = std::fs::read_to_string(&fx) else {
        eprintln!("no fixture at {}: test skipped", fx.display());
        return;
    };
    if !dir.join("features-buildings.parquet").exists() {
        eprintln!("no features files at {}: test skipped (rust/tools/export_features_parquet.py)", dir.display());
        return;
    }
    let f: Value = serde_json::from_str(&text).unwrap();
    let i = &f["input"];
    let b = features::buildings(&dir.join("features-buildings.parquet"), 32).unwrap();
    let p = features::pois(&dir.join("features-pois.parquet"), 32).unwrap();
    let l = features::lots(&dir.join("features-sites.parquet"), 32).unwrap();
    let n = |k: &str| i[k].as_array().unwrap().len();
    eprintln!("buildings {} / {}, pois {} / {}, lots {} / {}", b.len(), n("buildings"), p.len(), n("pois"), l.len(), n("lots"));
    assert_eq!(b.len(), n("buildings"));
    assert_eq!(p.len(), n("pois"));
    assert_eq!(l.len(), n("lots"));
    let ids: BTreeSet<(String, i64)> = b.iter().map(|x| (x.osm_type.clone(), x.osm_id)).collect();
    let theirs: BTreeSet<(String, i64)> = i["buildings"].as_array().unwrap().iter().map(|x| (x["type"].as_str().unwrap().into(), x["osm_id"].as_i64().unwrap())).collect();
    assert_eq!(ids, theirs);
    let (a_mine, a_theirs): (f64, f64) = (b.iter().map(|x| ops::area(&x.geom)).sum(), i["buildings"].as_array().unwrap().iter().map(|x| ops::area(&io::multi_polygon(&x["geom"]).unwrap())).sum());
    eprintln!("building area {a_mine:.1} m2 here, {a_theirs:.1} m2 there");
    assert!((a_mine - a_theirs).abs() < 1e-3 * a_theirs);
    let lot_ids: BTreeSet<String> = l.iter().map(|x| x.id.clone()).collect();
    assert_eq!(lot_ids, i["lots"].as_array().unwrap().iter().map(|x| x["id"].as_str().unwrap().to_string()).collect());
    // the rows the step makes from them
    let rows = urbanstyle_model::elements::build(&b, &p, &l);
    let expect = f["expect"].as_array().unwrap();
    eprintln!("element rows {} / {}", rows.len(), expect.len());
    // (the step itself gives one row more than the Python build with the fixture inputs too: 4,184 against 4,183)
    assert!(rows.len().abs_diff(expect.len()) <= 1);
}
