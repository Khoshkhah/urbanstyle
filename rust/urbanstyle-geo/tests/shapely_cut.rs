//! The helpers against shapely, on the real polygons of a cut: the Casino cut of Monaco (data/cuts/sr-casino.urban.duckdb). The data
//! is made by rust/tools/export_geo_fixture.py and is not in git: with no file, each test says so and passes.
use serde_json::Value;
use std::time::Instant;
use urbanstyle_geo::{io, lines, ops};
use urbanstyle_geo::ops::Mp;

fn fixture() -> Option<Value> {
    let path = std::env::var("URBANSTYLE_GEO_FIXTURE").unwrap_or_else(|_| "../../data/cuts/geo-fixture.json".into());
    match std::fs::read_to_string(&path) {
        Ok(s) => serde_json::from_str(&s).ok(),
        Err(_) => {
            eprintln!("no fixture at {path}: run rust/tools/export_geo_fixture.py; test skipped");
            None
        }
    }
}

fn near(a: f64, b: f64, rel: f64, abs: f64, what: &str) {
    assert!((a - b).abs() <= abs.max(rel * b.abs()), "{what}: {a} against shapely's {b}");
}

fn blocks(f: &Value) -> Vec<Mp> {
    f["blocks"].as_array().unwrap().iter().map(|b| Mp::new(vec![io::polygon(b).unwrap()])).collect()
}

fn expect(f: &Value, k: &str) -> f64 {
    f["expect"][k].as_f64().unwrap()
}

fn expects(f: &Value, k: &str) -> Vec<f64> {
    f["expect"][k].as_array().unwrap().iter().map(|x| x.as_f64().unwrap()).collect()
}

fn lines_of(f: &Value) -> Vec<geo::LineString<f64>> {
    f["lines"].as_array().unwrap().iter().map(|l| io::line_string(l).unwrap()).collect()
}

#[test]
fn street_is_the_area_less_the_blocks() {
    let Some(f) = fixture() else { return };
    let boxx = io::multi_polygon(&f["box"]).unwrap();
    let bl = blocks(&f);
    let t = Instant::now();
    let u = ops::union_all(bl.iter());
    let street = ops::difference(&boxx, &u);
    let dt = t.elapsed();
    near(ops::area(&u), expect(&f, "union_blocks_area"), 1e-6, 0.01, "the union of the blocks");
    near(ops::area(&street), expect(&f, "street_area"), 1e-6, 0.01, "the street");
    assert_eq!(street.0.len() as f64, expect(&f, "street_polys"), "the number of polygons of the street");
    let lanes_b = io::multi_polygon(&f["lanes_b"]).unwrap();
    let inter = ops::intersection(&street, &lanes_b);
    near(ops::area(&inter), expect(&f, "inter_area"), 1e-5, 0.05, "the street and the lanes buffered by 8 m");
    eprintln!("union, difference and intersection of the cut: {dt:?}");
}

#[test]
fn line_buffers() {
    let Some(f) = fixture() else { return };
    let ls = lines_of(&f);
    let (flat, round) = (expects(&f, "flat"), expects(&f, "round"));
    for (i, l) in ls.iter().enumerate() {
        near(ops::area(&ops::buffer_line_flat(l, 1.5)), flat[i], 3e-3, 0.1, &format!("line {i} flat"));
        near(ops::area(&ops::buffer_line(l, 2.5)), round[i], 3e-3, 0.1, &format!("line {i} round"));
    }
}

#[test]
fn wide_and_negative_buffer() {
    let Some(f) = fixture() else { return };
    let bl = blocks(&f);
    let (wide, neg) = (expects(&f, "wide"), expects(&f, "neg"));
    let t = Instant::now();
    for (i, b) in bl.iter().enumerate() {
        near(ops::area(&ops::wide(b, 8.0)), wide[i], 5e-3, 0.5, &format!("block {i} wide"));
        near(ops::area(&ops::buffer(b, -3.0)), neg[i], 5e-3, 0.5, &format!("block {i} shrunk by 3 m"));
    }
    eprintln!("wide and a negative buffer of {} blocks: {:?}", bl.len(), t.elapsed());
}

#[test]
fn position_along_a_line() {
    let Some(f) = fixture() else { return };
    let ls = lines_of(&f);
    for p in f["projects"].as_array().unwrap() {
        let l = &ls[p["line"].as_u64().unwrap() as usize];
        let q = p["point"].as_array().unwrap();
        let c = geo::Coord { x: q[0].as_f64().unwrap(), y: q[1].as_f64().unwrap() };
        let s = lines::project(l, c);
        near(s, p["s"].as_f64().unwrap(), 1e-9, 1e-6, "project");
        let back = lines::interpolate(l, s).unwrap();
        assert!(((back.x - c.x).powi(2) + (back.y - c.y).powi(2)).sqrt() < 5.0, "interpolate lands near the point");
    }
}
