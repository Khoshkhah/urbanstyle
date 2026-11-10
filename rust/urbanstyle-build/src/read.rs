//! The readers of the raw inputs: JSON files that the Python exporters wrote from SimReady's tables and duckOSM's (rust/tools/export_*_fixture.py).
//! They stand in for the readers of the tables themselves (Parquet or Arrow). The parsing is that of the tests of each crate.
#![allow(clippy::all)]
use serde_json::Value;
use std::collections::BTreeMap;
use urbanstyle_geo::io;
use urbanstyle_geo::ops::Mp;

pub mod blocks_in {
    use super::*;
    use urbanstyle_blocks::{Input, PathWay, Street};
pub fn input(f: &Value) -> Input {
    let i = &f["input"];
    let mp = |k: &str| io::multi_polygon(&i[k]).unwrap();
    let list = |k: &str| -> Vec<Mp> { i[k].as_array().unwrap().iter().map(|m| io::multi_polygon(m).unwrap()).collect() };
    Input {
        area: mp("area"),
        face: mp("face"),
        lanes: list("lanes"),
        junctions: list("junctions"),
        drives: list("drives"),
        streets: i["streets"]
            .as_array()
            .unwrap()
            .iter()
            .map(|s| Street {
                way: s["way"].as_i64().unwrap(),
                name: s["name"].as_str().map(String::from),
                class: s["class"].as_str().unwrap_or("").to_string(),
                line: io::line_string(&s["line"]).unwrap(),
            })
            .collect(),
        paths: i["paths"]
            .as_array()
            .unwrap()
            .iter()
            .map(|p| PathWay {
                way: p["way"].as_i64().unwrap(),
                class: p["class"].as_str().unwrap_or("").to_string(),
                name: p["name"].as_str().map(String::from),
                geom: geo::MultiLineString::new(p["geom"].as_array().unwrap().iter().map(|l| io::line_string(l).unwrap()).collect()),
                width: p["width"].as_f64(),
            })
            .collect(),
    }
}
}

pub mod division_in {
    use super::*;
    use urbanstyle_division::*;
fn mp(v: &Value) -> Mp {
    io::multi_polygon(v).unwrap()
}
fn ls(v: &Value) -> geo::LineString<f64> {
    io::line_string(v).unwrap()
}
fn lss(v: &Value) -> Vec<geo::LineString<f64>> {
    v.as_array().unwrap().iter().map(ls).collect()
}
fn s(v: &Value) -> String {
    v.as_str().unwrap_or("").to_string()
}
fn os(v: &Value) -> Option<String> {
    v.as_str().map(String::from)
}
fn tags(v: &Value) -> BTreeMap<String, String> {
    v.as_object().unwrap().iter().map(|(k, x)| (k.clone(), x.as_str().unwrap_or("").to_string())).collect()
}

pub fn input(f: &Value) -> Input {
    let i = &f["input"];
    let arr = |k: &str| i[k].as_array().unwrap().clone();
    Input {
        area: mp(&i["area"]),
        blocks: mp(&i["blocks"]),
        corridors: mp(&i["corridors"]),
        carriageways: arr("carriageways")
            .iter()
            .map(|c| Carriageway {
                id: c["id"].as_i64().unwrap(),
                way: c["way"].as_i64(),
                twin: c["twin"].as_i64(),
                shared: c["shared"].as_bool().unwrap(),
                highway: s(&c["highway"]),
                name: os(&c["name"]),
                oneway: c["oneway"].as_bool().unwrap(),
                edges: c["edges"].as_array().map_or(vec![], |a| a.iter().map(|x| x.as_i64().unwrap()).collect()),
                ring: c["ring"].as_bool().unwrap(),
                inside: c["inside"].as_i64(),
                level: c["level"].as_i64().unwrap() as i32,
                line: ls(&c["line"]),
            })
            .collect(),
        lanes: arr("lanes")
            .iter()
            .map(|l| Lane {
                id: l["id"].as_i64().unwrap(),
                cid: l["cid"].as_i64().unwrap(),
                n: l["n"].as_i64().unwrap(),
                role: s(&l["role"]),
                turn: os(&l["turn"]),
                w: l["w"].as_f64().unwrap(),
                method: s(&l["method"]),
                srcs: l["srcs"].as_array().unwrap().iter().map(s).collect(),
                left: ls(&l["left"]),
                right: ls(&l["right"]),
                geom: mp(&l["geom"]),
            })
            .collect(),
        junctions: arr("junctions")
            .iter()
            .map(|j| Junction {
                id: j["id"].as_i64().unwrap(),
                nodes: j["nodes"].as_array().unwrap().iter().map(|n| n.as_i64().unwrap()).collect(),
                kind: s(&j["kind"]),
                control: os(&j["control"]),
                level: j["level"].as_i64().unwrap() as i32,
                method: s(&j["method"]),
                area: mp(&j["area"]),
            })
            .collect(),
        islands: arr("islands")
            .iter()
            .map(|x| Island { j: x["j"].as_i64(), kind: s(&x["kind"]), level: x["level"].as_i64().unwrap() as i32, method: s(&x["method"]), geom: mp(&x["geom"]) })
            .collect(),
        stops: arr("stops").iter().map(|x| Stop { cid: x["cid"].as_i64().unwrap(), j: x["j"].as_i64(), method: s(&x["method"]), lines: lss(&x["lines"]) }).collect(),
        moves: arr("moves")
            .iter()
            .map(|x| Move {
                j: x["j"].as_i64().unwrap(),
                fl: x["fl"].as_i64().unwrap(),
                tl: x["tl"].as_i64().unwrap(),
                fc: x["fc"].as_i64().unwrap(),
                tc: x["tc"].as_i64().unwrap(),
                turn: s(&x["turn"]),
                uses: x["uses"].as_array().map_or(vec![], |a| a.iter().map(|u| u.as_str().unwrap_or("").to_string()).collect()),
                method: s(&x["method"]),
                lines: lss(&x["lines"]),
            })
            .collect(),
        faces: arr("faces").iter().map(|x| Face { level: x["level"].as_i64().unwrap() as i32, geom: mp(&x["geom"]) }).collect(),
        crossing_ways: arr("crossing_ways").iter().map(|x| CrossingWay { id: x["id"].as_i64().unwrap(), lines: lss(&x["lines"]), tags: tags(&x["tags"]) }).collect(),
        crossing_nodes: arr("crossing_nodes")
            .iter()
            .map(|x| CrossingNode { id: x["id"].as_i64().unwrap(), tags: tags(&x["tags"]), xy: geo::Coord { x: x["xy"][0].as_f64().unwrap(), y: x["xy"][1].as_f64().unwrap() } })
            .collect(),
    }
}
}

pub mod ground_in {
    use super::*;
    use urbanstyle_ground::*;
fn mp(v: &Value) -> Mp {
    io::multi_polygon(v).unwrap()
}
fn os(v: &Value) -> Option<String> {
    v.as_str().map(String::from)
}

pub fn input(f: &Value) -> Input {
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
}

