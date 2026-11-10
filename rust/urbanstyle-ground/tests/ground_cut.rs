//! The Rust ground against the Python reference (ground.assemble) on a cut: the same inputs, the same rules. The data is made by
//! rust/tools/export_ground_fixture.py and is not in git: with no file the test says so and passes. The Python result is not exactly
//! repeatable (a few alleys differ by metres from run to run), so the areas are compared with a tolerance.
use serde_json::Value;
use std::collections::BTreeMap;
use std::time::Instant;
use urbanstyle_geo::io;
use urbanstyle_geo::ops::{self, Mp};
use urbanstyle_ground::*;

fn fixture() -> Option<Value> {
    let path = std::env::var("URBANSTYLE_GROUND_FIXTURE").unwrap_or_else(|_| "../../data/cuts/ground-fixture.json".into());
    match std::fs::read_to_string(&path) {
        Ok(s) => serde_json::from_str(&s).ok(),
        Err(_) => {
            eprintln!("no fixture at {path}: run rust/tools/export_ground_fixture.py; test skipped");
            None
        }
    }
}

fn mp(v: &Value) -> Mp {
    io::multi_polygon(v).unwrap()
}
fn os(v: &Value) -> Option<String> {
    v.as_str().map(String::from)
}

fn input(f: &Value) -> Input {
    let i = &f["input"];
    Input {
        area: mp(&i["area"]),
        land: (!i["land"].is_null()).then(|| mp(&i["land"])),
        has_parcels: i["has_parcels"].as_bool().unwrap(),
        order: i["order"]
            .as_array()
            .unwrap()
            .iter()
            .map(|k| Kind {
                typ: k["type"].as_str().unwrap().into(),
                source: k["source"].as_str().unwrap().into(),
                method: k["method"].as_str().unwrap().into(),
                items: k["items"].as_array().unwrap().iter().map(|x| Item { r#ref: x["ref"].as_str().unwrap().into(), name: os(&x["name"]), geom: mp(&x["geom"]) }).collect(),
            })
            .collect(),
        lines: i["lines"]
            .as_array()
            .unwrap()
            .iter()
            .map(|l| Line {
                typ: l["type"].as_str().unwrap().into(),
                r#ref: l["ref"].as_str().unwrap().into(),
                name: os(&l["name"]),
                lines: l["lines"].as_array().unwrap().iter().map(|x| io::line_string(x).unwrap()).collect(),
                width: l["width"].as_f64(),
            })
            .collect(),
    }
}

fn base(id: &str) -> String {
    id.split('/').next().unwrap().to_string()
}

#[test]
fn the_ground_agrees_with_the_python_reference() {
    let Some(f) = fixture() else { return };
    let inp = input(&f);
    let t = Instant::now();
    let out = build(&inp);
    eprintln!("the ground: {:?} ({} rows)", t.elapsed(), out.len());

    // the ground items, by id without the piece number: the area of each and its type
    let mut ours: BTreeMap<String, (String, f64)> = BTreeMap::new();
    for g in &out {
        use geo::Area;
        let e = ours.entry(base(&g.id)).or_insert((g.typ.clone(), 0.0));
        e.1 += g.geom.unsigned_area();
    }
    let mut theirs: BTreeMap<String, (String, f64)> = BTreeMap::new();
    for x in f["expect"].as_array().unwrap() {
        let e = theirs.entry(base(x["id"].as_str().unwrap())).or_insert((x["type"].as_str().unwrap().into(), 0.0));
        e.1 += x["area"].as_f64().unwrap();
    }
    let missing: Vec<_> = theirs.keys().filter(|k| !ours.contains_key(*k)).take(8).collect();
    let extra: Vec<_> = ours.keys().filter(|k| !theirs.contains_key(*k)).take(8).collect();
    let n_missing = theirs.keys().filter(|k| !ours.contains_key(*k)).count();
    let n_extra = ours.keys().filter(|k| !theirs.contains_key(*k)).count();
    eprintln!("ground items: reference {}, ours {}; missing {n_missing} {:?}; extra {n_extra} {:?}", theirs.len(), ours.len(), missing, extra);

    // by type
    let mut by_type: BTreeMap<String, (f64, f64, usize, usize)> = BTreeMap::new();
    for (_, (t, a)) in &theirs {
        let x = by_type.entry(t.clone()).or_default();
        x.0 += a;
        x.2 += 1;
    }
    for (_, (t, a)) in &ours {
        let x = by_type.entry(t.clone()).or_default();
        x.1 += a;
        x.3 += 1;
    }
    for (t, (ra, oa, rn, on)) in &by_type {
        eprintln!("  {t:18}: area {oa:10.0} against {ra:10.0} m2 ({:+.2}%), items {on} against {rn}", 100.0 * (oa - ra) / ra.max(1e-9));
    }
    let off: Vec<_> = theirs.iter().filter(|(k, (_, a))| ours.get(*k).map_or(false, |(_, oa)| (oa - a).abs() > (0.01 * a).max(1.0))).map(|(k, (_, a))| format!("{k} ref {a:.0} ours {:.0}", ours[k].1)).collect();
    eprintln!("items whose area is off by more than 1% or 1 m2: {} of {}; the first: {:?}", off.len(), theirs.len(), &off[..off.len().min(8)]);

    let mut dd: Vec<(f64, String)> = Vec::new();
    for (k, (t, a)) in theirs.iter().filter(|(_, (t, _))| t != "yard") {
        let o = ours.get(k).map_or(0.0, |x| x.1);
        dd.push(((o - a).abs(), format!("{k} ({t}) ref {a:.0} ours {o:.0}")));
    }
    for (k, (t, a)) in ours.iter().filter(|(_, (t, _))| t != "yard") {
        if !theirs.contains_key(k) {
            dd.push((*a, format!("{k} ({t}) ref none ours {a:.0}")));
        }
    }
    dd.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap());
    eprintln!("the largest differences: {:#?}", dd.iter().take(14).map(|x| &x.1).collect::<Vec<_>>());
    // the partition: the rows cover the area once
    use geo::Area;
    let total: f64 = out.iter().map(|g| g.geom.unsigned_area()).sum();
    let area = ops::area(&inp.area);
    let union = ops::union_all(out.iter().map(|g| Mp::new(vec![g.geom.clone()])).collect::<Vec<_>>().iter());
    let gaps = ops::area(&ops::difference(&inp.area, &union));
    eprintln!("the area {area:.1} m2; the rows add up to {total:.1}; their union {:.1}; gaps {gaps:.2} m2; overlaps {:.2} m2", ops::area(&union), total - ops::area(&union));

    // which rows overlap
    let boxes: Vec<_> = out.iter().map(|g| geo::BoundingRect::bounding_rect(&g.geom)).collect();
    let index = urbanstyle_geo::index::Index::new(boxes.iter().copied());
    let mut pairs: Vec<(f64, String)> = Vec::new();
    for (i, g) in out.iter().enumerate() {
        let gm = Mp::new(vec![g.geom.clone()]);
        for j in index.query(&boxes[i].unwrap()) {
            if j <= i {
                continue;
            }
            let a = ops::area(&ops::intersection(&gm, &Mp::new(vec![out[j].geom.clone()])));
            if a > 0.05 {
                pairs.push((a, format!("{} ({}) x {} ({}): {a:.1} m2", g.id, g.typ, out[j].id, out[j].typ)));
            }
        }
    }
    pairs.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap());
    eprintln!("overlapping pairs: {}; the largest: {:#?}", pairs.len(), pairs.iter().take(8).map(|x| &x.1).collect::<Vec<_>>());

    // the limits: each kind to 0.1% and one sliver of 30 m2 (the Python result varies by metres between two runs, and a sliver that
    // touches two neighbours for nearly the same length goes to either); the rows partition the area
    for (t, (ra, oa, _, _)) in &by_type {
        assert!((oa - ra).abs() <= 0.001 * ra.max(1000.0) + 30.0, "{t}: area {oa} against {ra}");
    }
    assert!(off.len() <= 2, "{} items differ by more than 1%", off.len());
    assert!(gaps < 1.0 && total - ops::area(&union) < 1.0 && pairs.is_empty(), "the rows do not partition the area");
}
