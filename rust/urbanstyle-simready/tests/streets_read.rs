//! The streets of the roads against the model fixture's `work.arm` and `work.street` (rust/tools/export_model_fixture.py).
use serde_json::Value;
use std::path::PathBuf;
use urbanstyle_simready::{osm, streets};

fn env(k: &str, d: &str) -> PathBuf {
    PathBuf::from(std::env::var(k).unwrap_or_else(|_| d.into()))
}

#[test]
fn streets_from_the_driving_edges() {
    let (fx, pass0) = (env("URBANSTYLE_MODEL_FIXTURE", "../../data/cuts/monaco-model-fixture.json"), env("URBANSTYLE_PASS0_DIR", "../../../simready/build/monaco/pass0-rust"));
    let Ok(text) = std::fs::read_to_string(&fx) else {
        eprintln!("no fixture at {}: test skipped", fx.display());
        return;
    };
    if !pass0.join("raw_ways.parquet").exists() {
        eprintln!("no duckOSM files: test skipped");
        return;
    }
    let f: Value = serde_json::from_str(&text).unwrap();
    let ways = osm::ways(&pass0.join("raw_ways.parquet"), 32).unwrap();
    let edges = osm::driving_edges(&pass0.join("edges_driving.parquet"), 32).unwrap();
    let t = std::time::Instant::now();
    let s = streets::read(&edges, &ways);
    eprintln!("streets in {:.2} s", t.elapsed().as_secs_f64());
    let theirs: Vec<(String, String)> = f["input"]["way_street"].as_array().unwrap().iter().filter_map(|x| Some((format!("w{}", x["osm_id"]), x["street"].as_str()?.to_string()))).collect();
    let same = theirs.iter().filter(|(w, st)| s.way_street.get(w) == Some(st)).count();
    let missing = theirs.iter().filter(|(w, _)| !s.way_street.contains_key(w)).count();
    eprintln!("way_street: {} here, {} there, {same} the same street, {missing} ways missing here", s.way_street.len(), theirs.len());
    let names: Vec<(String, i32, String)> = f["input"]["name_street"].as_array().unwrap().iter().filter_map(|x| Some((x["name"].as_str()?.to_string(), x["level"].as_i64()? as i32, x["street"].as_str()?.to_string()))).collect();
    // (a name that several unconnected streets of one level share goes to the last of them in the table, which has no order: any of them is right)
    let mut by_key: std::collections::BTreeMap<(String, i32), std::collections::BTreeSet<String>> = std::collections::BTreeMap::new();
    for (n, l, st) in &names {
        by_key.entry((n.clone(), *l)).or_default().insert(st.clone());
    }
    let same_n = by_key.iter().filter(|(k, set)| s.name_street.get(*k).map_or(false, |st| set.contains(st))).count();
    eprintln!("name_street: {} keys here, {} there ({} with more than one street), {same_n} keys with one of the same streets", s.name_street.len(), by_key.len(), by_key.values().filter(|v| v.len() > 1).count());
    assert!(same * 100 >= theirs.len() * 90, "{same} of {}", theirs.len());
    assert!(same_n * 100 >= by_key.len() * 90, "{same_n} of {}", by_key.len());
}
