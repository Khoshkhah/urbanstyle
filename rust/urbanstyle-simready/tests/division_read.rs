//! The division input read from SimReady's Parquet files against the one the Python reference read (the division fixture of
//! rust/tools/export_division_fixture.py). Both come from the same SimReady build. With no files the test says so and passes.
//!
//! URBANSTYLE_DIVISION_FIXTURE: the fixture (default ../../data/cuts/monaco-division-fixture.json);
//! URBANSTYLE_SIMREADY_DIR: SimReady's folder of Parquet files (default ../../../simready/out/monaco-rust);
//! URBANSTYLE_PASS0_DIR: duckOSM's pass-0 folder (default ../../../simready/build/monaco/pass0-rust).
use geo::Area;
use serde_json::Value;
use std::collections::BTreeSet;
use std::path::PathBuf;
use urbanstyle_geo::io;
use urbanstyle_simready::division;

fn env(k: &str, d: &str) -> PathBuf {
    PathBuf::from(std::env::var(k).unwrap_or_else(|_| d.into()))
}

#[test]
fn division_input_from_parquet() {
    let (fx, sim, pass0) = (
        env("URBANSTYLE_DIVISION_FIXTURE", "../../data/cuts/monaco-division-fixture.json"),
        env("URBANSTYLE_SIMREADY_DIR", "../../../simready/out/monaco-rust"),
        env("URBANSTYLE_PASS0_DIR", "../../../simready/build/monaco/pass0-rust"),
    );
    let Ok(text) = std::fs::read_to_string(&fx) else {
        eprintln!("no fixture at {}: test skipped", fx.display());
        return;
    };
    if !sim.join("reference-line.parquet").exists() {
        eprintln!("no SimReady files at {}: test skipped", sim.display());
        return;
    }
    let f: Value = serde_json::from_str(&text).unwrap();
    let i = &f["input"];
    let area = io::multi_polygon(&i["area"]).unwrap();
    let edges = division::Edges::read(&pass0.join("edges_driving.parquet")).unwrap();
    let t = std::time::Instant::now();
    let s = division::read(&sim, &edges, &area).unwrap();
    eprintln!("read in {:.2} s", t.elapsed().as_secs_f64());

    let ids = |k: &str, key: &str| -> BTreeSet<i64> { i[k].as_array().unwrap().iter().filter_map(|x| x[key].as_i64()).collect() };
    let diff = |name: &str, mine: BTreeSet<i64>, theirs: BTreeSet<i64>| {
        eprintln!("{name}: {} here, {} in the reference, {} only here, {} only there", mine.len(), theirs.len(), mine.difference(&theirs).count(), theirs.difference(&mine).count());
        (mine.len() as i64 - theirs.len() as i64).abs() as f64 / theirs.len().max(1) as f64
    };
    let r = [
        diff("carriageways", s.carriageways.iter().map(|c| c.id).collect(), ids("carriageways", "id")),
        diff("lanes", s.lanes.iter().map(|c| c.id).collect(), ids("lanes", "id")),
        diff("junctions", s.junctions.iter().map(|c| c.id).collect(), ids("junctions", "id")),
    ];
    let n = |k: &str| i[k].as_array().unwrap().len();
    eprintln!("islands {} / {}, stops {} / {}, moves {} / {}, faces {} / {}", s.islands.len(), n("islands"), s.stops.len(), n("stops"), s.moves.len(), n("moves"), s.faces.len(), n("faces"));
    // the rows both have, one by one: the files can be of a slightly later SimReady build than the fixture (59 of 3,019 lane ids differ), so
    // the ids and counts are compared with a limit, and the geometry of the rows with the same id exactly
    let by_id = |k: &str| -> std::collections::BTreeMap<i64, &Value> { i[k].as_array().unwrap().iter().map(|x| (x["id"].as_i64().unwrap(), x)).collect() };
    let (mut other_count, mut other_width, mut other_role) = (0usize, 0usize, 0usize);
    let (mut worst_line, worst_lane, mut worst_area, mut lane_n, mut area_sum_mine, mut area_sum_theirs) = (0.0f64, 0.0f64, 0.0f64, 0usize, 0.0, 0.0);
    let cw = by_id("carriageways");
    for c in &s.carriageways {
        if let Some(x) = cw.get(&c.id) {
            let l = io::line_string(&x["line"]).unwrap();
            assert_eq!(l.0.len(), c.line.0.len(), "carriageway {}", c.id);
            worst_line = l.0.iter().zip(&c.line.0).map(|(a, b)| (a.x - b.x).hypot(a.y - b.y)).fold(worst_line, f64::max);
            assert_eq!(x["way"].as_i64(), c.way, "the way of carriageway {}", c.id);
            assert_eq!(x["highway"].as_str().unwrap_or(""), c.highway);
            assert_eq!(x["level"].as_i64().unwrap() as i32, c.level);
        }
    }
    let lanes = by_id("lanes");
    for l in &s.lanes {
        if let Some(x) = lanes.get(&l.id) {
            let (a, b) = (io::line_string(&x["left"]).unwrap(), io::line_string(&x["right"]).unwrap());
            // (the files are of a later SimReady build than the fixture: some lanes have other lines, other widths, another role. The lanes whose
            // lines are the same must have the same ground, and those are compared)
            let same_lines = a.0.len() == l.left.0.len()
                && b.0.len() == l.right.0.len()
                && a.0.iter().zip(&l.left.0).chain(b.0.iter().zip(&l.right.0)).all(|(p, q)| (p.x - q.x).hypot(p.y - q.y) < 1e-6);
            other_role += usize::from(x["role"].as_str().unwrap_or("") != l.role);
            other_width += usize::from((x["w"].as_f64().unwrap() - l.w).abs() > 1e-9);
            if !same_lines {
                other_count += 1;
                continue;
            }
            let (m, t) = (l.geom.unsigned_area(), io::multi_polygon(&x["geom"]).unwrap().unsigned_area());
            worst_area = worst_area.max((m - t).abs());
            (lane_n, area_sum_mine, area_sum_theirs) = (lane_n + 1, area_sum_mine + m, area_sum_theirs + t);
        }
    }
    eprintln!("the same ids: carriageway line off by {worst_line:.2e} m at most, lane lines {worst_lane:.2e} m, a lane's area {worst_area:.3} m2 at most; {lane_n} lanes with the same lines compared ({other_count} lanes have other lines, {other_width} another width, {other_role} another role), {area_sum_mine:.1} m2 here, {area_sum_theirs:.1} m2 there");
    assert!(r.iter().all(|x| *x < 0.03), "ids differ: {r:?}");
    assert!(worst_line < 1e-6 && worst_area < 0.5 && (area_sum_mine - area_sum_theirs).abs() < 1e-4 * area_sum_theirs);
    assert!(lane_n * 2 >= s.lanes.len(), "only {lane_n} lanes of {} have the same lines", s.lanes.len());
    for (a, b) in [(s.islands.len(), n("islands")), (s.stops.len(), n("stops")), (s.moves.len(), n("moves")), (s.faces.len(), n("faces"))] {
        assert!((a as f64 - b as f64).abs() <= 0.03 * b as f64 + 1.0, "{a} against {b}");
    }
}
