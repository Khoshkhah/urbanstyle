//! The pedestrian ways and crossing nodes read from duckOSM's raw files against the Python reference (the division and blocks fixtures).
use serde_json::Value;
use std::collections::BTreeSet;
use std::path::PathBuf;
use urbanstyle_geo::io;
use urbanstyle_simready::osm;

fn env(k: &str, d: &str) -> PathBuf {
    PathBuf::from(std::env::var(k).unwrap_or_else(|_| d.into()))
}

#[test]
fn ways_and_nodes_from_parquet() {
    let (dfx, bfx, pass0) = (
        env("URBANSTYLE_DIVISION_FIXTURE", "../../data/cuts/monaco-division-fixture.json"),
        env("URBANSTYLE_BLOCKS_FIXTURE", "../../data/cuts/monaco-blocks-fixture.json"),
        env("URBANSTYLE_PASS0_DIR", "../../../simready/build/monaco/pass0-rust"),
    );
    let (Ok(d), Ok(b)) = (std::fs::read_to_string(&dfx), std::fs::read_to_string(&bfx)) else {
        eprintln!("no fixtures: test skipped");
        return;
    };
    if !pass0.join("raw_ways.parquet").exists() {
        eprintln!("no duckOSM files: test skipped");
        return;
    }
    let (d, b): (Value, Value) = (serde_json::from_str(&d).unwrap(), serde_json::from_str(&b).unwrap());
    let area = io::multi_polygon(&d["input"]["area"]).unwrap();
    let t = std::time::Instant::now();
    let ways = osm::ways(&pass0.join("raw_ways.parquet"), 32).unwrap();
    let driving = osm::driving_ways(&pass0.join("edges_driving.parquet")).unwrap();
    let nodes = osm::crossing_nodes(&pass0.join("raw_nodes.parquet"), 32).unwrap();
    eprintln!("read in {:.2} s: {} ways, {} crossing nodes", t.elapsed().as_secs_f64(), ways.len(), nodes.len());

    // the crossings: the same ways
    let cw = osm::crossing_ways(&ways, &driving, &area);
    let mine: BTreeSet<i64> = cw.iter().map(|w| w.id).collect();
    let theirs: BTreeSet<i64> = d["input"]["crossing_ways"].as_array().unwrap().iter().map(|x| x["id"].as_i64().unwrap()).collect();
    eprintln!("crossing ways: {} here, {} there, {} only here, {} only there", mine.len(), theirs.len(), mine.difference(&theirs).count(), theirs.difference(&mine).count());
    assert_eq!(mine, theirs);

    // the crossing nodes: the same nodes at the same places
    let their_nodes: std::collections::BTreeMap<i64, (f64, f64)> =
        d["input"]["crossing_nodes"].as_array().unwrap().iter().map(|x| (x["id"].as_i64().unwrap(), (x["xy"][0].as_f64().unwrap(), x["xy"][1].as_f64().unwrap()))).collect();
    let worst = nodes.iter().filter_map(|n| their_nodes.get(&n.id).map(|p| (n.xy.x - p.0).hypot(n.xy.y - p.1))).fold(0.0f64, f64::max);
    eprintln!("crossing nodes: {} here, {} there, off by {worst:.2e} m at most", nodes.len(), their_nodes.len());
    assert_eq!(nodes.len(), their_nodes.len());
    assert!(worst < 1e-3);

    // the paths: the real ways (the Python also has duckOSM's virtual edges, with a negative id)
    let paths = osm::paths(&ways, &driving, &area);
    let mine: BTreeSet<i64> = paths.iter().map(|p| p.way).collect();
    let theirs: BTreeSet<i64> = b["input"]["paths"].as_array().unwrap().iter().map(|x| x["way"].as_i64().unwrap()).collect();
    let real: BTreeSet<i64> = theirs.iter().copied().filter(|w| *w > 0).collect();
    eprintln!("paths: {} here, {} there ({} virtual), {} real ones only here, {} only there", mine.len(), theirs.len(), theirs.len() - real.len(), mine.difference(&real).count(), real.difference(&mine).count());
    assert!(real.difference(&mine).count() * 50 <= real.len(), "too many paths missing");
}
