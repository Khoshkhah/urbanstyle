//! The blocks input read from Parquet files against the one the Python reference read (the blocks fixture of
//! rust/tools/export_blocks_fixture.py), and the area from duckOSM's boundary against the fixture's area. With no files the test passes
//! and says so. URBANSTYLE_BLOCKS_FIXTURE, URBANSTYLE_SIMREADY_DIR and URBANSTYLE_PASS0_DIR as in `division_read`.
use geo::{Area, CoordsIter};
use serde_json::Value;
use std::collections::BTreeSet;
use std::path::PathBuf;
use urbanstyle_geo::{io, ops};
use urbanstyle_simready::{blocks, boundary, division};

fn env(k: &str, d: &str) -> PathBuf {
    PathBuf::from(std::env::var(k).unwrap_or_else(|_| d.into()))
}

#[test]
fn blocks_input_from_parquet() {
    let (fx, sim, pass0) = (
        env("URBANSTYLE_BLOCKS_FIXTURE", "../../data/cuts/monaco-blocks-fixture.json"),
        env("URBANSTYLE_SIMREADY_DIR", "../../../simready/out/monaco-rust"),
        env("URBANSTYLE_PASS0_DIR", "../../../simready/build/monaco/pass0-rust"),
    );
    let Ok(text) = std::fs::read_to_string(&fx) else {
        eprintln!("no fixture at {}: test skipped", fx.display());
        return;
    };
    if !sim.join("reference-line.parquet").exists() || !pass0.join("boundary_main.parquet").exists() {
        eprintln!("no SimReady or duckOSM files: test skipped");
        return;
    }
    let f: Value = serde_json::from_str(&text).unwrap();
    let i = &f["input"];

    // the area: every corner within a millimetre of the Python (PROJ) result
    let theirs = io::multi_polygon(&i["area"]).unwrap();
    let area = boundary::read(&pass0.join("boundary_main.parquet"), None).unwrap();
    let (a, b): (Vec<_>, Vec<_>) = (area.coords_iter().collect(), theirs.coords_iter().collect());
    assert_eq!(a.len(), b.len());
    let worst = a.iter().zip(&b).map(|(p, q)| (p.x - q.x).hypot(p.y - q.y)).fold(0.0f64, f64::max);
    eprintln!("area: {} corners, off by {worst:.2e} m at most", a.len());
    assert!(worst < 1e-3);

    let edges = division::Edges::read(&pass0.join("edges_driving.parquet")).unwrap();
    let t = std::time::Instant::now();
    let s = blocks::read(&sim, &edges, &theirs).unwrap();
    eprintln!("read in {:.2} s", t.elapsed().as_secs_f64());
    let n = |k: &str| i[k].as_array().unwrap().len();
    eprintln!("lanes {} / {}, drives {} / {}, junctions {} / {}, streets {} / {}", s.lanes.len(), n("lanes"), s.drives.len(), n("drives"), s.junctions.len(), n("junctions"), s.streets.len(), n("streets"));
    let (mine, theirs_face) = (ops::area(&s.face), io::multi_polygon(&i["face"]).unwrap().unsigned_area());
    eprintln!("face {mine:.1} m2 here, {theirs_face:.1} m2 there");
    let ways: BTreeSet<i64> = s.streets.iter().map(|x| x.way).collect();
    let their_ways: BTreeSet<i64> = i["streets"].as_array().unwrap().iter().map(|x| x["way"].as_i64().unwrap()).collect();
    eprintln!("street ways: {} here, {} there, {} only here, {} only there", ways.len(), their_ways.len(), ways.difference(&their_ways).count(), their_ways.difference(&ways).count());
    for (a, b) in [(s.lanes.len(), n("lanes")), (s.drives.len(), n("drives")), (s.junctions.len(), n("junctions")), (s.streets.len(), n("streets"))] {
        assert!((a as f64 - b as f64).abs() <= 0.05 * b as f64 + 1.0, "{a} against {b}");
    }
    assert!((mine - theirs_face).abs() < 0.01 * theirs_face);
}
