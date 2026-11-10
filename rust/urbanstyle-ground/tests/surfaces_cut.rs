//! The Rust surfaces (layer 1) against the Python `urban.surface`: the same ground items, parts and OSM layers go in. The data is made by
//! rust/tools/export_surface_fixture.py and is not in git: with no file the test says so and passes.
use serde_json::Value;
use std::collections::BTreeMap;
use std::time::Instant;
use urbanstyle_geo::io;
use urbanstyle_ground::surfaces::*;

fn fixture() -> Option<Value> {
    let path = std::env::var("URBANSTYLE_SURFACE_FIXTURE").unwrap_or_else(|_| "../../data/cuts/surface-fixture.json".into());
    match std::fs::read_to_string(&path) {
        Ok(s) => serde_json::from_str(&s).ok(),
        Err(_) => {
            eprintln!("no fixture at {path}: run rust/tools/export_surface_fixture.py; test skipped");
            None
        }
    }
}

fn os(v: &Value) -> Option<String> {
    v.as_str().map(String::from)
}

fn layer(v: &Value) -> Layer {
    Layer { items: v.as_array().unwrap().iter().map(|x| (x["ref"].as_str().unwrap().to_string(), io::multi_polygon(&x["geom"]).unwrap())).collect() }
}

fn input(f: &Value) -> SurfaceInput {
    let i = &f["input"];
    let l = &i["layers"];
    SurfaceInput {
        ground: i["ground"].as_array().unwrap().iter().map(|g| GroundItem { id: g["id"].as_str().unwrap().into(), typ: g["type"].as_str().unwrap().into(), r#ref: os(&g["ref"]), source: os(&g["source"]), method: os(&g["method"]), geom: io::multi_polygon(&g["geom"]).unwrap() }).collect(),
        parts: i["parts"].as_array().unwrap().iter().map(|p| StreetPart { unit: p["unit"].as_str().unwrap().into(), typ: p["type"].as_str().unwrap().into(), source: os(&p["source"]), geom: io::multi_polygon(&p["geom"]).unwrap() }).collect(),
        layers: Layers {
            verge: layer(&l["verge"]),
            garden: layer(&l["garden"]),
            play: layer(&l["play"]),
            buildings: layer(&l["buildings"]),
            lots: layer(&l["lots"]),
            sites: layer(&l["sites"]),
            walks: l["walks"].as_array().unwrap().iter().map(|w| (w["ref"].as_str().unwrap().to_string(), w["lines"].as_array().unwrap().iter().map(|x| io::line_string(x).unwrap()).collect())).collect(),
        },
    }
}

#[test]
fn the_surfaces_agree_with_the_python_table() {
    let Some(f) = fixture() else { return };
    let inp = input(&f);
    let t = Instant::now();
    let out = build(&inp);
    eprintln!("the surfaces: {:?} ({} rows)", t.elapsed(), out.len());
    // the pieces of one surface (`<ground>:<kind>/1`, `/2`, ...) are numbered by their middles rounded to a decimetre: matched by area
    let base = |id: &str| id.rsplit_once('/').filter(|(_, n)| n.chars().all(|c| c.is_ascii_digit())).map_or(id.to_string(), |(b, _)| b.to_string());
    let mut ours: BTreeMap<String, Vec<&Surface>> = BTreeMap::new();
    for s in &out {
        ours.entry(base(&s.id)).or_default().push(s);
    }
    let mut theirs: BTreeMap<String, Vec<&Value>> = BTreeMap::new();
    let exp = f["expect"].as_array().unwrap();
    for x in exp {
        theirs.entry(base(x["id"].as_str().unwrap())).or_default().push(x);
    }
    for v in ours.values_mut() {
        v.sort_by(|a, b| geo::Area::unsigned_area(&b.geom).partial_cmp(&geo::Area::unsigned_area(&a.geom)).unwrap());
    }
    for v in theirs.values_mut() {
        v.sort_by(|a, b| b["area"].as_f64().unwrap().partial_cmp(&a["area"].as_f64().unwrap()).unwrap());
    }
    let missing: Vec<&String> = theirs.keys().filter(|k| !ours.contains_key(*k)).collect();
    let extra: Vec<&String> = ours.keys().filter(|k| !theirs.contains_key(*k)).collect();
    let count_bad: Vec<String> = theirs.iter().filter(|(k, v)| ours.get(*k).map_or(false, |o| o.len() != v.len())).map(|(k, v)| format!("{k}: {} against {}", ours[k].len(), v.len())).collect();
    let (mut bad, mut ta, mut tb, mut pairs) = (vec![], 0.0, 0.0, 0);
    for (id, es) in &theirs {
        let Some(os_) = ours.get(id) else { continue };
        for (x, o) in es.iter().zip(os_.iter()) {
            pairs += 1;
            let a = geo::Area::unsigned_area(&o.geom);
            ta += a;
            tb += x["area"].as_f64().unwrap();
            if o.kind != x["kind"].as_str().unwrap() || o.ground != x["ground"].as_str().unwrap() || o.source != x["source"].as_str().unwrap() || o.method != x["method"].as_str().unwrap() || o.r#ref.as_deref() != x["ref"].as_str() || (a - x["area"].as_f64().unwrap()).abs() > 0.2 + 0.001 * a {
                bad.push(format!("{id}: {} {} {} area {a:.2} against {}", o.kind, o.source, o.method, x["area"]));
            }
        }
    }
    let mut kinds: BTreeMap<String, (f64, f64)> = BTreeMap::new();
    for s in &out {
        kinds.entry(s.kind.clone()).or_default().0 += geo::Area::unsigned_area(&s.geom);
    }
    for x in exp {
        kinds.entry(x["kind"].as_str().unwrap().to_string()).or_default().1 += x["area"].as_f64().unwrap();
    }
    eprintln!("by kind (ours, reference): {:?}", kinds.iter().map(|(k, v)| format!("{k} {:.0} {:.0}", v.0, v.1)).collect::<Vec<_>>());
    eprintln!("surfaces: reference {} rows in {} ids, ours {} rows in {}; ids missing {} {:?}, extra {} {:?}; pieces per id differ {} {:?}; {pairs} pieces matched, differ {} {:?}; area {ta:.0} against {tb:.0} m2", exp.len(), theirs.len(), out.len(), ours.len(), missing.len(), &missing[..missing.len().min(3)], extra.len(), &extra[..extra.len().min(3)], count_bad.len(), &count_bad[..count_bad.len().min(3)], bad.len(), &bad[..bad.len().min(3)]);
    assert!(missing.len() + extra.len() <= theirs.len() / 100 + 1 && count_bad.len() <= theirs.len() / 50 + 1 && bad.len() <= pairs / 20 + 1, "the surfaces differ");
    let (all_o, all_r): (f64, f64) = (kinds.values().map(|v| v.0).sum(), kinds.values().map(|v| v.1).sum());
    assert!((all_o - all_r).abs() <= 0.0002 * all_r, "the area of the surfaces differs: {all_o} against {all_r}");
    let _ = (ta, tb);
    // each kind to 0.05%; a garden is part of the yard in a build whose OSM data has no garden (the Monaco build of 2026-11-07), so the two
    // are compared together
    let (mut g_o, mut g_r) = (0.0, 0.0);
    for (k, v) in &kinds {
        if k == "garden" || k == "yard" {
            g_o += v.0;
            g_r += v.1;
        } else {
            assert!((v.0 - v.1).abs() <= 0.0005 * v.1.max(1000.0), "{k}: {} against {}", v.0, v.1);
        }
    }
    assert!((g_o - g_r).abs() <= 0.0005 * g_r, "garden and yard: {g_o} against {g_r}");
}
