//! The Rust paths against the Python reference (paths.assemble) on a cut. The data is made by rust/tools/export_paths_fixture.py and is not
//! in git: with no file the test says so and passes.
use serde_json::Value;
use std::collections::{BTreeMap, HashMap};
use std::time::Instant;
use urbanstyle_geo::io;
use urbanstyle_geo::ops;
use urbanstyle_paths::*;

fn fixture() -> Option<Value> {
    let path = std::env::var("URBANSTYLE_PATHS_FIXTURE").unwrap_or_else(|_| "../../data/cuts/paths-fixture.json".into());
    match std::fs::read_to_string(&path) {
        Ok(s) => serde_json::from_str(&s).ok(),
        Err(_) => {
            eprintln!("no fixture at {path}: run rust/tools/export_paths_fixture.py; test skipped");
            None
        }
    }
}

fn os(v: &Value) -> Option<String> {
    v.as_str().map(String::from)
}

fn input(f: &Value) -> Input {
    let i = &f["input"];
    Input {
        level: i["level"].as_i64().unwrap() as i32,
        footway_w: i["footway_w"].as_f64().unwrap(),
        items: i["items"].as_array().unwrap().iter().map(|x| PathItem { id: x["id"].as_str().unwrap().into(), r#ref: x["ref"].as_str().unwrap().into(), geom: io::multi_polygon(&x["geom"]).unwrap() }).collect(),
        corridors: i["corridors"]
            .as_object()
            .unwrap()
            .iter()
            .map(|(k, c)| (k.clone(), Corridor { name: os(&c["name"]), width: c["width"].as_f64(), source: os(&c["source"]), method: os(&c["method"]) }))
            .collect::<HashMap<_, _>>(),
        lines: i["lines"]
            .as_array()
            .unwrap()
            .iter()
            .map(|l| PathLine { way: l["way"].as_str().unwrap().into(), class: os(&l["class"]), name: os(&l["name"]), src: l["src"].as_i64(), dst: l["dst"].as_i64(), line: io::line_string(&l["line"]).unwrap() })
            .collect(),
    }
}

#[test]
fn the_paths_agree_with_the_python_reference() {
    let Some(f) = fixture() else { return };
    let inp = input(&f);
    let t = Instant::now();
    let out = build(&inp);
    eprintln!("the paths: {:?} ({} spaces)", t.elapsed(), out.len());
    let exp = f["expect"].as_array().unwrap();

    // the faces of one base id (`p0-w1`, `p0-w1.2`, ...) are matched by area: the number after the dot follows the order of the polygonize
    let base = |id: &str| id.split('.').next().unwrap().to_string();
    let mut ours: BTreeMap<String, Vec<&PathSpace>> = BTreeMap::new();
    for p in &out {
        ours.entry(base(&p.id)).or_default().push(p);
    }
    let mut theirs: BTreeMap<String, Vec<&Value>> = BTreeMap::new();
    for e in exp {
        theirs.entry(base(e["id"].as_str().unwrap())).or_default().push(e);
    }
    for v in ours.values_mut() {
        v.sort_by(|a, b| ops::area(&b.geom).partial_cmp(&ops::area(&a.geom)).unwrap());
    }
    for v in theirs.values_mut() {
        v.sort_by(|a, b| b["area"].as_f64().unwrap().partial_cmp(&a["area"].as_f64().unwrap()).unwrap());
    }
    let missing: Vec<_> = theirs.keys().filter(|k| !ours.contains_key(*k)).collect();
    let extra: Vec<_> = ours.keys().filter(|k| !theirs.contains_key(*k)).collect();
    let count_off: Vec<_> = theirs.iter().filter(|(k, v)| ours.get(*k).map_or(false, |o| o.len() != v.len())).map(|(k, v)| format!("{k} ref {} ours {}", v.len(), ours[k].len())).collect();
    eprintln!("ids: reference {} ({} spaces), ours {} ({} spaces); missing {} {:?}; extra {} {:?}; faces per id differ {} {:?}", theirs.len(), exp.len(), ours.len(), out.len(), missing.len(), &missing[..missing.len().min(6)], extra.len(), &extra[..extra.len().min(6)], count_off.len(), &count_off[..count_off.len().min(4)]);

    let (mut area_off, mut kind_off, mut ways_off, mut nodes_off, mut links_off, mut len_off, mut n_pairs) = (vec![], 0, 0, 0, 0, 0, 0);
    let (mut ta, mut tb) = (0.0, 0.0);
    for (id, es) in &theirs {
        let Some(os_) = ours.get(id) else { continue };
        for (e, o) in es.iter().zip(os_.iter()) {
            n_pairs += 1;
            let a = ops::area(&o.geom);
            let ra = e["area"].as_f64().unwrap();
            ta += a;
            tb += ra;
            if (a - ra).abs() > (0.01 * ra).max(0.5) {
                area_off.push(format!("{id} ref {ra:.1} ours {a:.1}"));
            }
            let kind = if o.kind == Kind::Intersection { "path intersection" } else { "path section" };
            kind_off += (e["kind"].as_str().unwrap() != kind) as usize;
            let ways: Vec<String> = e["ways"].as_array().unwrap().iter().map(|x| x.as_str().unwrap().to_string()).collect();
            ways_off += (ways != o.ways) as usize;
            let nodes: Vec<i64> = e["nodes"].as_array().unwrap().iter().map(|x| x.as_i64().unwrap()).collect();
            nodes_off += (nodes != o.nodes) as usize;
            // (the links name faces by their numbers: compare their count)
            links_off += (e["links"].as_array().unwrap().len() != o.links.len()) as usize;
            if let (Some(rl), Some(l)) = (e["length"].as_f64(), o.length) {
                len_off += ((rl - l).abs() > 0.2) as usize;
            }
        }
    }
    eprintln!("{n_pairs} faces matched; area {ta:.0} against {tb:.0} m2; off by more than 1% or 0.5 m2: {} {:?}", area_off.len(), &area_off[..area_off.len().min(6)]);
    eprintln!("kind differs {kind_off}; ways {ways_off}; nodes {nodes_off}; links (count) {links_off}; length off by 0.2 m {len_off}");
    // the limits: the way that names a face is the one with the most length in it, and two ways of the same length tie (4 ids, 13 lists of ways)
    assert!(n_pairs >= out.len() - 6 && exp.len().abs_diff(out.len()) <= 2, "the spaces differ");
    assert!((ta - tb).abs() <= 0.001 * tb && area_off.is_empty(), "the areas differ");
    assert!(kind_off == 0 && nodes_off == 0 && links_off == 0 && len_off == 0, "kinds, nodes, links or lengths differ");
    assert!(ways_off <= 15 && missing.len() <= 6, "too many ties went the other way");
}
