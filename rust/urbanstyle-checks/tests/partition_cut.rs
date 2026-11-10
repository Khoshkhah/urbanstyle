//! The partition checks of the Rust crate against the counts that Python's `urbanstyle check` gave for the same build. The data is made by
//! rust/tools/export_check_fixture.py and is not in git: with no file the test says so and passes.
use serde_json::Value;
use std::collections::BTreeMap;
use std::time::Instant;
use urbanstyle_checks::*;
use urbanstyle_geo::io;

fn fixture() -> Option<Value> {
    let path = std::env::var("URBANSTYLE_CHECK_FIXTURE").unwrap_or_else(|_| "../../data/cuts/check-fixture.json".into());
    match std::fs::read_to_string(&path) {
        Ok(s) => serde_json::from_str(&s).ok(),
        Err(_) => {
            eprintln!("no fixture at {path}: run rust/tools/export_check_fixture.py; test skipped");
            None
        }
    }
}

fn os(v: &Value) -> Option<String> {
    v.as_str().map(String::from)
}
fn mp(v: &Value) -> urbanstyle_geo::ops::Mp {
    io::multi_polygon(v).unwrap()
}

fn input(f: &Value) -> Input {
    let i = &f["input"];
    let a = |k: &str| i[k].as_array().unwrap();
    Input {
        area: mp(&i["area"]),
        units: a("units").iter().map(|u| Unit { id: u["id"].as_str().unwrap().into(), kind: u["kind"].as_str().unwrap().into(), level: u["level"].as_i64().unwrap() as i32, geom: mp(&u["geom"]) }).collect(),
        parts: a("parts").iter().map(|p| PartIn { unit: p["unit"].as_str().unwrap().into(), id: p["id"].as_str().unwrap().into(), level: p["level"].as_i64().unwrap() as i32, typ: p["type"].as_str().unwrap().into(), width_method: os(&p["width_method"]), source: os(&p["source"]), width: p["width"].as_f64(), geom: mp(&p["geom"]) }).collect(),
        ground: a("ground").iter().map(|g| GroundIn { id: g["id"].as_str().unwrap().into(), level: g["level"].as_i64().unwrap() as i32, typ: g["type"].as_str().unwrap().into(), geom: mp(&g["geom"]) }).collect(),
        surfaces: a("surfaces").iter().map(|s| SurfaceIn { id: s["id"].as_str().unwrap().into(), ground: s["ground"].as_str().unwrap().into(), geom: mp(&s["geom"]) }).collect(),
        blocks: a("blocks").iter().map(|b| BlockIn { id: b["id"].as_str().unwrap().into(), geom: mp(&b["geom"]) }).collect(),
        buildings: a("buildings").iter().map(mp).collect(),
        node_pt: i["node_pt"].as_object().unwrap().iter().map(|(k, v)| (k.parse().unwrap(), geo::Coord { x: v[0].as_f64().unwrap(), y: v[1].as_f64().unwrap() })).collect(),
        junctions: a("junctions").iter().map(|j| JunctionIn { intersection: j["intersection"].as_str().unwrap().into(), level: j["level"].as_i64().unwrap() as i32, node: j["node"].as_i64().unwrap() }).collect(),
        subsections: a("subsections").iter().map(|s| SubsectionIn { id: s["id"].as_str().unwrap().into(), level: s["level"].as_i64().unwrap() as i32, line: (!s["line"].is_null()).then(|| io::line_string(&s["line"]).unwrap()), width: s["width"].as_f64() }).collect(),
        marks: a("marks").iter().map(|m| MarkIn { unit: m["unit"].as_str().unwrap().into(), typ: m["type"].as_str().unwrap().into(), source: os(&m["source"]), lines: m["lines"].as_array().unwrap().iter().map(|l| io::line_string(l).unwrap()).collect() }).collect(),
        guides: a("guides").iter().map(|g| (g["level"].as_i64().unwrap() as i32, g["lines"].as_array().unwrap().iter().map(|l| io::line_string(l).unwrap()).collect())).collect(),
        roads: a("roads").iter().map(|r| RoadIn { osm_id: r["osm_id"].as_i64().unwrap(), src: r["src"].as_i64(), dst: r["dst"].as_i64(), class: os(&r["class"]), width: r["width"].as_f64(), subtype: os(&r["subtype"]), level: r["level"].as_i64().unwrap() as i32, typ: r["type"].as_str().unwrap().into(), street: r["street"].as_bool().unwrap(), line: (!r["line"].is_null()).then(|| io::line_string(&r["line"]).unwrap()) }).collect(),
        sections: i["sections"].as_object().unwrap().iter().map(|(k, v)| (k.clone(), v.as_str().unwrap().to_string())).collect(),
        shared_m: roadway::SHARED_M,
        approaches: a("approaches").iter().map(|x| ApproachIn { unit: x["unit"].as_str().unwrap().into(), from_edge: os(&x["from_edge"]), moves: x["moves"].as_i64(), ways: os(&x["ways"]), arrow: x["arrow"].as_bool(), no_arrow_because: os(&x["no_arrow_because"]) }).collect(),
    }
}

#[test]
fn the_partition_checks_agree_with_the_python_counts() {
    let Some(f) = fixture() else { return };
    let inp = input(&f);
    let t = Instant::now();
    let mut rows = partitions(&inp);
    rows.extend(roadway::roadway(&inp));
    rows.extend(roadway::joints(&inp));
    rows.push(roadway::lane_joints(&inp));
    rows.extend(rules::rules(&inp));
    eprintln!("the partition checks: {:?}", t.elapsed());
    let expect: BTreeMap<&str, i64> = f["expect"].as_object().unwrap().iter().map(|(k, v)| (k.as_str(), v.as_i64().unwrap())).collect();
    let mut off = vec![];
    for r in &rows {
        let e = expect.get(r.id).copied();
        eprintln!("  {:3} {:5} ours {:5} Python {:?}  {}", r.id, r.status(), r.count, e, &r.what[..r.what.len().min(70)]);
        if let Some(e) = e {
            if (r.count as i64 - e).abs() > (e / 50).max(1) {
                off.push(format!("{}: ours {} against {e}", r.id, r.count));
            }
        }
    }
    assert!(off.len() <= 2, "counts that differ: {off:?}");
}
