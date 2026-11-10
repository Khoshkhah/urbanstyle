//! The building and lot rows of `element` against the Python `urban.element`. The data is made by rust/tools/export_element_fixture.py and
//! is not in git: with no file the test says so and passes.
use serde_json::Value;
use std::collections::BTreeMap;
use std::time::Instant;
use urbanstyle_geo::{io, ops};
use urbanstyle_model::elements::*;

fn fixture() -> Option<Value> {
    let path = std::env::var("URBANSTYLE_ELEMENT_FIXTURE").unwrap_or_else(|_| "../../data/cuts/element-fixture.json".into());
    match std::fs::read_to_string(&path) {
        Ok(s) => serde_json::from_str(&s).ok(),
        Err(_) => {
            eprintln!("no fixture at {path}: run rust/tools/export_element_fixture.py; test skipped");
            None
        }
    }
}

fn os(v: &Value) -> Option<String> {
    v.as_str().map(String::from)
}

fn tags(v: &Value) -> BTreeMap<String, String> {
    v.as_object().unwrap().iter().map(|(k, x)| (k.clone(), x.as_str().unwrap_or("").to_string())).collect()
}

#[test]
fn the_elements_agree_with_the_python_table() {
    let Some(f) = fixture() else { return };
    let i = &f["input"];
    let buildings: Vec<BuildingIn> = i["buildings"].as_array().unwrap().iter().map(|b| BuildingIn { osm_type: b["type"].as_str().unwrap().into(), osm_id: b["osm_id"].as_i64().unwrap(), name: os(&b["name"]), kind: os(&b["kind"]), tags: tags(&b["tags"]), geom: io::multi_polygon(&b["geom"]).unwrap() }).collect();
    let pois: Vec<PoiIn> = i["pois"].as_array().unwrap().iter().map(|p| PoiIn { tags: tags(&p["tags"]), point: geo::Coord { x: p["point"][0].as_f64().unwrap(), y: p["point"][1].as_f64().unwrap() } }).collect();
    let lots: Vec<LotIn> = i["lots"].as_array().unwrap().iter().map(|l| LotIn { id: l["id"].as_str().unwrap().into(), typ: l["type"].as_str().unwrap().into(), name: os(&l["name"]), level: l["level"].as_i64().unwrap() as i32, geom: io::multi_polygon(&l["geom"]).unwrap() }).collect();
    let t = Instant::now();
    let out = build(&buildings, &pois, &lots);
    eprintln!("the elements: {:?} ({} rows)", t.elapsed(), out.len());
    let ours: BTreeMap<&str, &ElementRow> = out.iter().map(|r| (r.id.as_str(), r)).collect();
    let exp = f["expect"].as_array().unwrap();
    let mut bad: BTreeMap<&str, Vec<String>> = BTreeMap::new();
    let mut missing = vec![];
    for x in exp {
        let id = x["id"].as_str().unwrap();
        let Some(o) = ours.get(id) else { missing.push(id.to_string()); continue };
        let mut chk = |what: &'static str, ok: bool, ours: String, theirs: String| {
            if !ok {
                bad.entry(what).or_default().push(format!("{id}: ours {ours} against {theirs}"));
            }
        };
        chk("kind", o.kind == x["kind"].as_str().unwrap(), o.kind.clone(), x["kind"].to_string());
        chk("class", o.class.as_deref() == x["class"].as_str(), format!("{:?}", o.class), x["class"].to_string());
        chk("name", o.name.as_deref() == x["name"].as_str(), format!("{:?}", o.name), x["name"].to_string());
        chk("level_min", o.level_min as i64 == x["level_min"].as_i64().unwrap(), o.level_min.to_string(), x["level_min"].to_string());
        chk("level_max", o.level_max as i64 == x["level_max"].as_i64().unwrap(), o.level_max.to_string(), x["level_max"].to_string());
        chk("level_src", o.level_src == x["level_src"].as_str().unwrap(), o.level_src.clone(), x["level_src"].to_string());
        chk("floors", o.floors.map(|v| v as i64) == x["floors"].as_i64(), format!("{:?}", o.floors), x["floors"].to_string());
        chk("height", o.height_m == x["height"].as_f64(), format!("{:?}", o.height_m), x["height"].to_string());
        chk("use", o.usage.as_deref() == x["use"].as_str(), format!("{:?}", o.usage), x["use"].to_string());
        chk("use_source", o.use_source.as_deref() == x["use_source"].as_str(), format!("{:?}", o.use_source), x["use_source"].to_string());
        chk("use_method", o.use_method.as_deref() == x["use_method"].as_str(), format!("{:?}", o.use_method), x["use_method"].to_string());
        chk("ground_use", o.ground_use.as_deref() == x["ground_use"].as_str(), format!("{:?}", o.ground_use), x["ground_use"].to_string());
        chk("ground_source", o.ground_source.as_deref() == x["ground_source"].as_str(), format!("{:?}", o.ground_source), x["ground_source"].to_string());
        chk("ground_method", o.ground_method.as_deref() == x["ground_method"].as_str(), format!("{:?}", o.ground_method), x["ground_method"].to_string());
        chk("area", (ops::area(&o.geom) - x["area"].as_f64().unwrap()).abs() < 0.05, String::new(), String::new());
    }
    let extra = ours.keys().filter(|k| !exp.iter().any(|x| x["id"] == **k)).count();
    eprintln!("elements: reference {}, ours {}; missing {} {:?}; extra {extra}; differ by field {:?}", exp.len(), out.len(), missing.len(), &missing[..missing.len().min(3)], bad.iter().map(|(k, v)| (*k, v.len(), v.first().cloned())).collect::<Vec<_>>());
    assert!(missing.len() + extra <= 2 && bad.values().map(|v| v.len()).sum::<usize>() <= exp.len() / 200 + 1, "the elements differ");
}
