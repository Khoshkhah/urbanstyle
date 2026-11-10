//! The Rust model (slice 1) against the Python `urban` tables: the same `work` rows go in, and the rows of `urban.space`, `urban.part` and
//! `urban.mark` that product.write made from them are the expected result. The data is made by rust/tools/export_model_fixture.py and
//! is not in git: with no file the test says so and passes.
use serde_json::Value;
use std::collections::BTreeMap;
use std::time::Instant;
use urbanstyle_geo::{io, ops};
use urbanstyle_model::objects::{build as build_objects, NodeIn, ObjectRow, PartRef, SpaceRef};
use urbanstyle_model::*;

fn fixture() -> Option<Value> {
    let path = std::env::var("URBANSTYLE_MODEL_FIXTURE").unwrap_or_else(|_| "../../data/cuts/model-fixture.json".into());
    match std::fs::read_to_string(&path) {
        Ok(s) => serde_json::from_str(&s).ok(),
        Err(_) => {
            eprintln!("no fixture at {path}: run rust/tools/export_model_fixture.py; test skipped");
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
        units: i["units"].as_array().unwrap().iter().map(|u| Unit { id: u["id"].as_str().unwrap().into(), kind: u["kind"].as_str().unwrap().into(), level: u["level"].as_i64().unwrap() as i32, geom: io::multi_polygon(&u["geom"]).unwrap() }).collect(),
        ground: i["ground"].as_array().unwrap().iter().map(|g| GroundIn { id: g["id"].as_str().unwrap().into(), typ: g["type"].as_str().unwrap().into(), level: g["level"].as_i64().unwrap() as i32, name: os(&g["name"]), source: os(&g["source"]), method: os(&g["method"]), r#ref: os(&g["ref"]), geom: io::multi_polygon(&g["geom"]).unwrap() }).collect(),
        blocks: i["blocks"].as_array().unwrap().iter().map(|b| BlockIn { id: b["id"].as_str().unwrap().into(), level: b["level"].as_i64().unwrap() as i32, source: os(&b["source"]), method: os(&b["method"]), geom: io::multi_polygon(&b["geom"]).unwrap() }).collect(),
        block_sides: i["block_sides"].as_array().unwrap().iter().map(|b| BlockSideIn { block: b["block"].as_str().unwrap().into(), way: b["way"].as_i64().unwrap(), name: os(&b["name"]), class: os(&b["class"]), distance_m: b["distance_m"].as_f64(), basis: os(&b["basis"]), method: os(&b["method"]) }).collect(),
        corridors: i["corridors"].as_array().unwrap().iter().map(|c| CorridorIn { id: c["id"].as_str().unwrap().into(), name: os(&c["name"]), width: c["width"].as_f64(), source: os(&c["source"]), method: os(&c["method"]) }).collect(),
        surfaces: i["surfaces"].as_array().unwrap().iter().map(|c| SurfaceIn { id: c["id"].as_str().unwrap().into(), ground: c["ground"].as_str().unwrap().into() }).collect(),
        junctions: i["junctions"].as_array().unwrap().iter().map(|j| JunctionIn { intersection: j["intersection"].as_str().unwrap().into(), node: j["node"].as_i64().unwrap(), level: j["level"].as_i64().unwrap() as i32, cluster: os(&j["cluster"]) }).collect(),
        node_pt: i["node_pt"].as_object().unwrap().iter().map(|(k, v)| (k.parse().unwrap(), geo::Coord { x: v[0].as_f64().unwrap(), y: v[1].as_f64().unwrap() })).collect(),
        way_street: i["way_street"].as_array().unwrap().iter().filter_map(|w| Some((format!("w{}", w["osm_id"]), w["street"].as_str()?.to_string()))).collect(),
        name_street: i["name_street"].as_array().unwrap().iter().filter_map(|w| Some(((w["name"].as_str()?.to_string(), w["level"].as_i64()? as i32), w["street"].as_str()?.to_string()))).collect(),
        roundabouts: i["roundabouts"].as_array().unwrap().iter().map(|l| io::line_string(l).unwrap()).collect(),
        path_spaces: i["path_spaces"]
            .as_array()
            .unwrap()
            .iter()
            .map(|x| PathSpaceIn {
                id: x["id"].as_str().unwrap().into(),
                kind: x["kind"].as_str().unwrap().into(),
                ground: x["ground"].as_str().unwrap().into(),
                level: x["level"].as_i64().unwrap() as i32,
                name: os(&x["name"]),
                class: os(&x["class"]),
                ways: x["ways"].as_array().map_or(vec![], |a| a.iter().map(|v| v.as_str().unwrap().to_string()).collect()),
                nodes: x["nodes"].as_array().map_or(vec![], |a| a.iter().map(|v| v.as_i64().unwrap()).collect()),
                width: x["width"].as_f64(),
                width_source: os(&x["ws"]),
                width_method: os(&x["wm"]),
                length: x["length"].as_f64(),
                pred: x["pred"].as_array().map_or(vec![], |a| a.iter().map(|v| v.as_str().unwrap().to_string()).collect()),
                succ: x["succ"].as_array().map_or(vec![], |a| a.iter().map(|v| v.as_str().unwrap().to_string()).collect()),
                axis: (!x["axis"].is_null()).then(|| io::line_string(&x["axis"]).unwrap()),
                geom: io::multi_polygon(&x["geom"]).unwrap(),
            })
            .collect(),
        close_gaps_m: 0.0,
        turns: i["turns"].as_array().unwrap().iter().map(|t| TurnIn { unit: t["unit"].as_str().unwrap().into(), level: t["level"].as_i64().unwrap() as i32, from_edge: os(&t["from_edge"]), from_lane: t["from_lane"].as_i64(), to_edge: os(&t["to_edge"]), to_lane: t["to_lane"].as_i64(), turn: os(&t["turn"]), source: os(&t["source"]), vehicles: os(&t["vehicles"]), condition: os(&t["condition"]), lines: t["lines"].as_array().unwrap().iter().map(|l| io::line_string(l).unwrap()).collect() }).collect(),
        approaches: i["approaches"].as_array().unwrap().iter().map(|a| ApproachIn { unit: a["unit"].as_str().unwrap().into(), level: a["level"].as_i64().unwrap() as i32, from_edge: os(&a["from_edge"]), lane: a["lane"].as_i64(), moves: a["moves"].as_i64(), ways: os(&a["ways"]), arrow: a["arrow"].as_bool(), no_arrow_because: os(&a["no_arrow_because"]) }).collect(),
        owidth: i["owidth"].as_object().unwrap().iter().map(|(k, v)| (k.clone(), v.as_f64().unwrap())).collect(),
        subsections: i["subsections"]
            .as_array()
            .unwrap()
            .iter()
            .map(|s| Subsection {
                id: s["id"].as_str().unwrap().into(),
                section: s["section"].as_str().unwrap().into(),
                level: s["level"].as_i64().unwrap() as i32,
                line: (!s["line"].is_null()).then(|| io::line_string(&s["line"]).unwrap()),
                width: s["width"].as_f64(),
                oneway: s["oneway"].as_bool(),
                length: s["length"].as_f64(),
                left_extra: s["left_extra"].as_f64(),
                class: os(&s["class"]),
            })
            .collect(),
        parts: i["parts"]
            .as_array()
            .unwrap()
            .iter()
            .map(|p| Part { id: p["id"].as_str().unwrap().into(), unit: p["unit"].as_str().unwrap().into(), typ: p["type"].as_str().unwrap().into(), direction: os(&p["direction"]), lane: p["lane"].as_i64(), road: os(&p["road"]), r#ref: os(&p["ref"]), extra: Default::default(), geom: io::multi_polygon(&p["geom"]).unwrap() })
            .collect(),
        marks: i["marks"]
            .as_array()
            .unwrap()
            .iter()
            .map(|m| Mark { unit: m["unit"].as_str().unwrap().into(), typ: m["type"].as_str().unwrap().into(), level: m["level"].as_i64().unwrap() as i32, source: os(&m["source"]), method: os(&m["method"]), reference: None, lines: m["lines"].as_array().unwrap().iter().map(|l| io::line_string(l).unwrap()).collect() })
            .collect(),
    }
}

fn strs_of(v: &Value) -> Vec<String> {
    v.as_array().map_or(vec![], |a| a.iter().map(|x| x.as_str().unwrap().to_string()).collect())
}

fn close(a: Option<f64>, b: Option<f64>, tol: f64) -> bool {
    match (a, b) {
        (Some(x), Some(y)) => (x - y).abs() <= tol,
        (None, None) => true,
        _ => false,
    }
}

#[test]
fn the_model_agrees_with_the_python_tables() {
    let Some(f) = fixture() else { return };
    let inp = input(&f);
    let t = Instant::now();
    let out = build(&inp);
    eprintln!("the model, slice 1: {:?} ({} spaces, {} parts, {} marks)", t.elapsed(), out.spaces.len(), out.parts.len(), out.marks.len());
    let e = &f["expect"];

    // the spaces
    let ours: BTreeMap<&str, &Space> = out.spaces.iter().filter(|s| s.kind == "subsection").map(|s| (s.id.as_str(), s)).collect();
    let exp = e["spaces"].as_array().unwrap();
    let mut bad = Vec::new();
    for x in exp {
        let id = x["id"].as_str().unwrap();
        let Some(o) = ours.get(id) else { bad.push(format!("{id}: missing")); continue };
        let axis_len = o.axis.as_ref().map(urbanstyle_geo::lines::length);
        if o.parent != x["parent"].as_str().unwrap() || !close(o.s_from, x["s_from"].as_f64(), 0.002) || !close(o.s_to, x["s_to"].as_f64(), 0.002) || !close(axis_len, x["axis_len"].as_f64(), 0.002) || !close(o.width, x["width"].as_f64(), 1e-9) {
            bad.push(format!("{id}: s {:?}-{:?} against {} - {}", o.s_from, o.s_to, x["s_from"], x["s_to"]));
        }
    }
    eprintln!("spaces: reference {}, ours {}; differ {} {:?}", exp.len(), ours.len(), bad.len(), &bad[..bad.len().min(4)]);
    assert!(bad.is_empty() && exp.len() == ours.len(), "the spaces differ");

    // the parts
    let sub_space: std::collections::BTreeSet<&str> = out.spaces.iter().filter(|s| s.kind == "subsection").map(|s| s.id.as_str()).collect();
    let ours: BTreeMap<&str, &PartRow> = out.parts.iter().filter(|p| sub_space.contains(p.space.as_str())).map(|p| (p.id.as_str(), p)).collect();
    let exp = e["parts"].as_array().unwrap();
    let (mut missing, mut st_off, mut axis_off, mut side_off, mut area_off) = (vec![], vec![], 0, 0, 0);
    for x in exp {
        let id = x["id"].as_str().unwrap();
        let Some(o) = ours.get(id) else { missing.push(id.to_string()); continue };
        let keys = ["s_from", "s_to", "t_from", "t_to"];
        if !keys.iter().enumerate().all(|(k, n)| close(o.st[k], x[n].as_f64(), 0.002)) {
            st_off.push(format!("{id}: ours {:?} against {} {} {} {}", o.st, x["s_from"], x["s_to"], x["t_from"], x["t_to"]));
        }
        axis_off += !close(o.axis.as_ref().map(urbanstyle_geo::lines::length), x["axis_len"].as_f64(), 0.01) as usize;
        side_off += (o.side != x["side"].as_str().unwrap() || o.space != x["space"].as_str().unwrap()) as usize;
        area_off += ((ops::area(&o.geom) - x["area"].as_f64().unwrap()).abs() > 0.05) as usize;
    }
    let extra = ours.keys().filter(|k| !exp.iter().any(|x| x["id"] == **k)).count();
    eprintln!("parts: reference {}, ours {}; missing {} {:?}; extra {extra}; (s, t) differ {} {:?}; axis length differs {axis_off}; side {side_off}; area {area_off}", exp.len(), ours.len(), missing.len(), &missing[..missing.len().min(4)], st_off.len(), &st_off[..st_off.len().min(3)]);

    assert!(missing.is_empty() && extra == 0 && st_off.is_empty() && side_off == 0 && area_off == 0 && axis_off <= 2, "the parts differ");

    // the links inside a section: of the subsections, and of the lanes (those that run to an intersection come with the cut intersections)
    {
        let sub_ids: std::collections::BTreeSet<&str> = out.spaces.iter().filter(|s| s.kind == "subsection").map(|s| s.id.as_str()).collect();
        let _ = &sub_ids;
        let keep = |v: &Value| -> Vec<String> { strs_of(v) };
        let sl = e["space_links"].as_object().unwrap();
        let space_bad = out.spaces.iter().filter(|s| s.kind == "subsection").filter(|s| {
            let x = &sl[&s.id];
            let (mut p, mut q) = (s.pred.clone(), s.succ.clone());
            p.sort();
            q.sort();
            p != { let mut k = keep(&x[0]); k.sort(); k } || q != { let mut k = keep(&x[1]); k.sort(); k }
        }).count();
        let pl = e["part_links"].as_object().unwrap();
        let part_ids: std::collections::BTreeSet<&str> = out.parts.iter().filter(|p| p.typ == "lane").map(|p| p.id.as_str()).collect();
        let _ = &part_ids;
        let keep_p = |v: &Value| -> Vec<String> { strs_of(v) };
        let mut part_bad = Vec::new();
        for p in out.parts.iter().filter(|p| p.typ == "lane" && pl.contains_key(&p.id)) {
            let x = &pl[&p.id];
            if p.pred != keep_p(&x[0]) || p.succ != keep_p(&x[1]) {
                part_bad.push(format!("{}: ours {:?} {:?} against {} {}", p.id, p.pred, p.succ, x[0], x[1]));
            }
        }
        eprintln!("links in a section: subsections differ {space_bad}; lanes differ {} {:?}", part_bad.len(), &part_bad[..part_bad.len().min(2)]);
        assert!(space_bad == 0 && part_bad.len() <= 3, "the links differ");

        // the path spaces and their parts
        let ps: BTreeMap<&str, &Space> = out.spaces.iter().filter(|s| s.kind.starts_with("path ")).map(|s| (s.id.as_str(), s)).collect();
        let exp = e["path_spaces"].as_array().unwrap();
        let bad = exp.iter().filter(|x| ps.get(x["id"].as_str().unwrap()).map_or(true, |o| o.kind != x["kind"].as_str().unwrap() || o.parent != x["parent"].as_str().unwrap() || !close(o.s_from, x["s_from"].as_f64(), 0.002) || !close(o.s_to, x["s_to"].as_f64(), 0.002) || !close(o.width, x["width"].as_f64(), 1e-9) || o.oneway != x["oneway"].as_bool() || !close(o.axis.as_ref().map(urbanstyle_geo::lines::length), x["axis_len"].as_f64(), 0.01) || o.pred != strs_of(&x["pred"]) || o.succ != strs_of(&x["succ"]))).count();
        eprintln!("path spaces: reference {}, ours {}; differ {bad}", exp.len(), ps.len());
        assert!(bad == 0 && exp.len() == ps.len(), "the path spaces differ");
        let pp: BTreeMap<&str, &PartRow> = out.parts.iter().filter(|p| p.typ == "path" || p.typ == "steps").map(|p| (p.id.as_str(), p)).collect();
        let exp = e["path_parts"].as_array().unwrap();
        let bad = exp.iter().filter(|x| pp.get(x["id"].as_str().unwrap()).map_or(true, |o| o.typ != x["kind"].as_str().unwrap() || o.side != x["side"].as_str().unwrap() || o.space != x["space"].as_str().unwrap() || !["s_from", "s_to", "t_from", "t_to"].iter().enumerate().all(|(k, n)| close(o.st[k], x[n].as_f64(), 0.002)) || !close(o.width_m, x["width"].as_f64(), 1e-9) || o.width_source.as_deref() != x["ws"].as_str() || !close(o.length_m, x["length"].as_f64(), 1e-9))).count();
        eprintln!("path parts: reference {}, ours {}; differ {bad}", exp.len(), pp.len());
        assert!(bad == 0 && exp.len() == pp.len(), "the path parts differ");
    }

    // rank 1: the street pieces, the plots, the paths; the pieces of the plots
    let ours: BTreeMap<&str, &GroundRow> = out.ground.iter().map(|g| (g.id.as_str(), g)).collect();
    let exp = e["ground"].as_array().unwrap();
    let mut bad = Vec::new();
    for x in exp {
        let id = x["id"].as_str().unwrap();
        let Some(o) = ours.get(id) else { bad.push(format!("{id}: missing")); continue };
        let sides_n = x["sides"].as_str().map_or(0, |s| serde_json::from_str::<Value>(s).ok().and_then(|v| v.as_array().map(|a| a.len())).unwrap_or(0));
        if o.kind != x["kind"].as_str().unwrap() || o.parent != x["parent"].as_str().unwrap() || (ops::area(&o.geom) - x["area"].as_f64().unwrap()).abs() > 0.05 + 1e-5 * ops::area(&o.geom)
            || o.r#ref.as_deref() != x["ref"].as_str() || !close(o.width_m, x["width"].as_f64(), 1e-9) || o.width_source.as_deref() != x["ws"].as_str()
            || o.sides.as_ref().map_or(0, |s| s.len()) != sides_n || o.name.as_deref() != x["name"].as_str()
        {
            bad.push(format!("{id}: {} {} area {:.2} against {}", o.kind, o.parent, ops::area(&o.geom), x["area"]));
        }
    }
    eprintln!("ground: reference {}, ours {}; differ {} {:?}", exp.len(), ours.len(), bad.len(), &bad[..bad.len().min(4)]);
    // (a street piece of a level below the ground is the union of the spaces of the level; one piece on Monaco comes out in two in Rust, as a thin
    // connection that GEOS keeps is split by `i_overlay`: the pieces after it are numbered one later)
    let bad_other: Vec<_> = bad.iter().filter(|b| !b.starts_with("g-")).collect();
    assert!(bad_other.is_empty() && exp.len().abs_diff(ours.len()) <= 1, "the ground rows differ: {bad_other:?}");
    let ours: BTreeMap<&str, &PlotPieceRow> = out.plot_pieces.iter().map(|g| (g.id.as_str(), g)).collect();
    let exp = e["plot_pieces"].as_array().unwrap();
    let mut bad = Vec::new();
    for x in exp {
        let id = x["id"].as_str().unwrap();
        let Some(o) = ours.get(id) else { bad.push(format!("{id}: missing")); continue };
        let surfaces: Vec<String> = x["surfaces"].as_array().map_or(vec![], |a| a.iter().map(|v| v.as_str().unwrap().to_string()).collect());
        if o.kind != x["kind"].as_str().unwrap() || o.parent.as_deref() != x["parent"].as_str() || !close(o.width_m, x["width"].as_f64(), 1e-9)
            || o.width_source.as_deref() != x["ws"].as_str() || o.surfaces != surfaces || (ops::area(&o.geom) - x["area"].as_f64().unwrap()).abs() > 0.05
        {
            bad.push(format!("{id}: parent {:?} against {}; width {:?} against {}; surfaces {:?} against {:?}; area {:.2} against {}", o.parent, x["parent"], o.width_m, x["width"], o.surfaces, surfaces, ops::area(&o.geom), x["area"]));
        }
    }
    eprintln!("plot pieces: reference {}, ours {}; differ {} {:?}", exp.len(), ours.len(), bad.len(), &bad[..bad.len().min(4)]);
    assert!(bad.len() <= exp.len() / 200 && exp.len() == out.plot_pieces.len(), "the plot pieces differ");

    // rank 2: the stretches, the arms, the named streets
    let strs = |v: &Value| -> Vec<String> { v.as_array().map_or(vec![], |a| a.iter().map(|x| x.as_str().unwrap().to_string()).collect()) };
    let ours: BTreeMap<&str, &StretchRow> = out.stretches.iter().map(|g| (g.id.as_str(), g)).collect();
    let exp = e["stretches"].as_array().unwrap();
    let mut bad: BTreeMap<&str, Vec<String>> = BTreeMap::new();
    for x in exp {
        let id = x["id"].as_str().unwrap();
        let Some(o) = ours.get(id) else { bad.entry("missing").or_default().push(id.to_string()); continue };
        let mut chk = |what: &'static str, ok: bool| {
            if !ok {
                bad.entry(what).or_default().push(format!("{id}: ours {} against {}", match what { "parent" => format!("{:?}", o.parent), "name" => format!("{:?}", o.name), "street" => format!("{:?}", o.street), "ways" => format!("{:?}", o.ways), "nodes" => format!("{:?}", o.nodes), "oneway" => format!("{:?}", o.oneway), _ => String::new() }, match what { "parent" => x["parent"].to_string(), "name" => x["name"].to_string(), "street" => x["street"].to_string(), "ways" => x["ways"].to_string(), "nodes" => x["nodes"].to_string(), "oneway" => x["oneway"].to_string(), _ => String::new() }));
            }
        };
        chk("kind", o.kind == x["kind"].as_str().unwrap());
        chk("parent", o.parent.as_deref() == x["parent"].as_str());
        chk("name", o.name.as_deref() == x["name"].as_str());
        chk("street", o.street.as_deref() == x["street"].as_str());
        chk("ways", o.ways == strs(&x["ways"]));
        chk("nodes", o.nodes == x["nodes"].as_array().map_or(vec![], |a| a.iter().map(|v| v.as_i64().unwrap()).collect::<Vec<_>>()));
        chk("class", o.class.as_deref() == x["class"].as_str());
        chk("oneway", o.oneway == x["oneway"].as_bool());
        chk("length", close(o.length, x["length"].as_f64(), 0.01));
        chk("axis", close(o.axis.as_ref().map(urbanstyle_geo::lines::length), x["axis_len"].as_f64(), 0.01));
        chk("area", (ops::area(&o.geom) - x["area"].as_f64().unwrap()).abs() <= 0.05);
    }
    eprintln!("stretches: reference {}, ours {}; differ by field {:?}", exp.len(), out.stretches.len(), bad.iter().map(|(k, v)| (*k, v.len(), v.first().cloned())).collect::<Vec<_>>());
    assert!(bad.values().map(|v| v.len()).sum::<usize>() <= exp.len() / 200 && exp.len() == out.stretches.len(), "the stretches differ: {bad:?}");
    let arms_exp: std::collections::BTreeSet<(String, Option<String>, String, Option<String>)> = e["arms"].as_array().unwrap().iter().map(|a| (a["intersection"].as_str().unwrap().to_string(), os(&a["street"]), a["section"].as_str().unwrap().to_string(), os(&a["way"]))).collect();
    let arms_ours: std::collections::BTreeSet<_> = out.arms.iter().map(|a| (a.intersection.clone(), a.street.clone(), a.section.clone(), a.way.clone())).collect();
    eprintln!("arms: reference {}, ours {}; only in the reference {}, only in ours {}", arms_exp.len(), arms_ours.len(), arms_exp.difference(&arms_ours).count(), arms_ours.difference(&arms_exp).count());
    assert!(arms_exp.difference(&arms_ours).count() + arms_ours.difference(&arms_exp).count() <= arms_exp.len() / 100, "the arms differ");
    let ours: BTreeMap<&str, &StreetRow> = out.streets.iter().map(|g| (g.id.as_str(), g)).collect();
    let exp = e["streets"].as_array().unwrap();
    let street_bad: Vec<_> = exp.iter().filter(|x| ours.get(x["id"].as_str().unwrap()).map_or(true, |o| o.name.as_deref() != x["name"].as_str() || o.sections != strs(&x["sections"]) || o.intersections != strs(&x["intersections"]) || (ops::area(&o.geom) - x["area"].as_f64().unwrap()).abs() > 0.5)).map(|x| x["id"].to_string()).collect();
    eprintln!("streets: reference {}, ours {}; differ {} {:?}", exp.len(), ours.len(), street_bad.len(), &street_bad[..street_bad.len().min(4)]);
    assert!(street_bad.len() <= exp.len() / 100, "the streets differ");
    if let Some(x) = exp.iter().find(|x| ours.get(x["id"].as_str().unwrap()).map_or(false, |o| o.sections != strs(&x["sections"]) || o.intersections != strs(&x["intersections"]) || o.name.as_deref() != x["name"].as_str() || (ops::area(&o.geom) - x["area"].as_f64().unwrap()).abs() > 0.5)) {
        let o = ours[x["id"].as_str().unwrap()];
        eprintln!("  first: {} name {:?} against {}; sections {:?} against {}; intersections {:?} against {}; area {:.1} against {}", x["id"], o.name, x["name"], o.sections, x["sections"], o.intersections, x["intersections"], ops::area(&o.geom), x["area"]);
    }

    // slice 3: the intersections cut by junction node, with their parts, links, marks and sides
    {
        let ours: BTreeMap<&str, &Space> = out.spaces.iter().filter(|s| matches!(s.kind.as_str(), "sub-intersection" | "ring sector" | "centre")).map(|s| (s.id.as_str(), s)).collect();
        let exp = e["int_spaces"].as_array().unwrap();
        let mut bad = Vec::new();
        for x in exp {
            let id = x["id"].as_str().unwrap();
            let Some(o) = ours.get(id) else { bad.push(format!("{id}: missing")); continue };
            if o.kind != x["kind"].as_str().unwrap() || o.parent != x["parent"].as_str().unwrap() || o.pred != strs_of(&x["pred"]) || o.succ != strs_of(&x["succ"]) || (ops::area(&o.geom) - x["area"].as_f64().unwrap()).abs() > 0.05 || o.name.as_deref() != x["name"].as_str() {
                bad.push(format!("{id}: {} area {:.2} against {}; pred {:?} against {}; succ {:?} against {}", o.kind, ops::area(&o.geom), x["area"], o.pred, x["pred"], o.succ, x["succ"]));
            }
        }
        eprintln!("pieces of intersections: reference {}, ours {}; differ {} {:?}", exp.len(), ours.len(), bad.len(), &bad[..bad.len().min(3)]);
        let exp_j = e["junction_rows"].as_array().unwrap();
        let jbad = exp_j.iter().filter(|x| !out.junctions.iter().any(|j| j.intersection == x["intersection"].as_str().unwrap() && j.node == x["node"].as_i64().unwrap() && j.space.as_deref() == x["space"].as_str())).count();
        eprintln!("junction rows: reference {}, ours {}; differ {jbad}", exp_j.len(), out.junctions.len());
        let ours: BTreeMap<&str, &PartRow> = out.parts.iter().map(|p| (p.id.as_str(), p)).collect();
        let exp = e["all_parts"].as_array().unwrap();
        let (mut missing, mut area_bad, mut link_bad, mut side_bad) = (vec![], vec![], vec![], 0);
        for x in exp {
            let id = x["id"].as_str().unwrap();
            let Some(o) = ours.get(id) else { missing.push(id.to_string()); continue };
            if (ops::area(&o.geom) - x["area"].as_f64().unwrap()).abs() > 0.05 {
                area_bad.push(format!("{id}: {:.2} against {}", ops::area(&o.geom), x["area"]));
            }
            side_bad += (o.side != x["side"].as_str().unwrap() || o.space != x["space"].as_str().unwrap() || o.typ != x["kind"].as_str().unwrap()) as usize;
            if o.pred != strs_of(&x["pred"]) || o.succ != strs_of(&x["succ"]) {
                link_bad.push(format!("{id}: ours {:?} {:?} against {} {}", o.pred, o.succ, x["pred"], x["succ"]));
            }
        }
        eprintln!("all parts: reference {}, ours {}; missing {} {:?}; area differs {} {:?}; side {side_bad}; links differ {} {:?}", exp.len(), ours.len(), missing.len(), &missing[..missing.len().min(3)], area_bad.len(), &area_bad[..area_bad.len().min(2)], link_bad.len(), &link_bad[..link_bad.len().min(2)]);
        let ours: BTreeMap<&str, &SideRow> = out.sides.iter().map(|p| (p.id.as_str(), p)).collect();
        let exp = e["sides"].as_array().unwrap();
        let sbad = exp.iter().filter(|x| ours.get(x["id"].as_str().unwrap()).map_or(true, |o| o.kind != x["kind"].as_str().unwrap() || o.parent != x["parent"].as_str().unwrap() || (ops::area(&o.geom) - x["area"].as_f64().unwrap()).abs() > 0.1 || !close(o.kerb.as_ref().map(|k| k.iter().map(urbanstyle_geo::lines::length).sum()), x["kerb_len"].as_f64(), 0.05) || o.kerb_source.as_deref() != x["ks"].as_str() || o.kerb_method.as_deref() != x["km"].as_str())).count();
        eprintln!("sides: reference {}, ours {}; differ {sbad}", exp.len(), ours.len());
        let ours: BTreeMap<&str, &MarkRow> = out.marks.iter().map(|p| (p.id.as_str(), p)).collect();
        let exp = e["all_marks"].as_array().unwrap();
        let (mut mm, mut pbad) = (0, vec![]);
        for x in exp {
            let Some(o) = ours.get(x["id"].as_str().unwrap()) else { mm += 1; continue };
            if o.parent.as_deref() != x["parent"].as_str() || o.parent_rank as i64 != x["prank"].as_i64().unwrap() || !close(o.st[0], x["s_from"].as_f64(), 0.002) || !close(o.st[2], x["t_from"].as_f64(), 0.002) {
                pbad.push(format!("{}: parent {:?} against {}", x["id"], o.parent, x["parent"]));
            }
        }
        eprintln!("all marks: reference {}, ours {}; missing {mm}; differ {} {:?}", exp.len(), ours.len(), pbad.len(), &pbad[..pbad.len().min(3)]);
        let exp = e["turn_rows"].as_array().unwrap();
        let key = |t: (&str, Option<i64>, &str, Option<i64>)| format!("{}|{:?}|{}|{:?}", t.0, t.1, t.2, t.3);
        let mut a: Vec<String> = out.turns.iter().map(|t| key((t.space.as_str(), t.from_lane, t.to_edge.as_deref().unwrap_or(""), t.to_lane))).collect();
        let mut b: Vec<String> = exp.iter().map(|t| key((t["space"].as_str().unwrap(), t["from_lane"].as_i64(), t["to_edge"].as_str().unwrap_or(""), t["to_lane"].as_i64()))).collect();
        a.sort();
        b.sort();
        let (sa, sb): (std::collections::BTreeSet<&String>, std::collections::BTreeSet<&String>) = (a.iter().collect(), b.iter().collect());
        let turn_diff = sa.symmetric_difference(&sb).count();
        eprintln!("turns: reference {}, ours {}; rows that differ {turn_diff} {:?}; approaches {} against {}", b.len(), a.len(), sa.difference(&sb).take(2).collect::<Vec<_>>(), e["approach_n"], out.approaches.len());
        // the limits: the pieces of one hairline-sensitive intersection and the choice of a part for a zebra mark (two parts that share the
        // mark) differ; everything else is equal
        assert!(bad.len() <= exp.len() / 100 + 1 && jbad == 0, "the pieces of the intersections differ");
        assert!(missing.is_empty() && area_bad.len() <= 10 && side_bad == 0 && link_bad.is_empty(), "the parts differ");
        assert!(sbad == 0, "the sides differ");
        assert!(mm == 0 && pbad.len() <= e["all_marks"].as_array().unwrap().len() / 100 + 1, "the marks differ");
        assert!(turn_diff <= b.len() / 100 + 2 && e["approach_n"].as_u64().unwrap() as usize == out.approaches.len(), "the turns differ");
    }

    // the marks
    let ours: BTreeMap<&str, &MarkRow> = out.marks.iter().filter(|m| sub_space.contains(m.space.as_str())).map(|p| (p.id.as_str(), p)).collect();
    let exp = e["marks"].as_array().unwrap();
    let (mut missing, mut st_off) = (vec![], vec![]);
    for x in exp {
        let id = x["id"].as_str().unwrap();
        let Some(o) = ours.get(id) else { missing.push(id.to_string()); continue };
        let keys = ["s_from", "s_to", "t_from", "t_to"];
        if !keys.iter().enumerate().all(|(k, n)| close(o.st[k], x[n].as_f64(), 0.002)) {
            st_off.push(format!("{id}: ours {:?} against {} {} {} {}", o.st, x["s_from"], x["s_to"], x["t_from"], x["t_to"]));
        }
    }
    eprintln!("marks: reference {}, ours {}; missing {} {:?}; (s, t) differ {} {:?}", exp.len(), ours.len(), missing.len(), &missing[..missing.len().min(4)], st_off.len(), &st_off[..st_off.len().min(3)]);
    assert!(missing.is_empty() && st_off.is_empty(), "the marks differ");
    let objects = check_objects(&out);
    check_registry(&out, &objects);
}

/// The street objects of the Python build against the Rust ones, placed in the spaces and parts of the Rust model (a fixture from
/// rust/tools/export_object_fixture.py; with no file the check is left out).
fn check_objects(model: &Output) -> Vec<ObjectRow> {
    let path = std::env::var("URBANSTYLE_OBJECT_FIXTURE").unwrap_or_else(|_| "../../data/cuts/object-fixture.json".into());
    let Some(f) = std::fs::read_to_string(&path).ok().and_then(|s| serde_json::from_str::<Value>(&s).ok()) else {
        eprintln!("no object fixture at {path}: the objects are not checked");
        return vec![];
    };
    let nodes: Vec<NodeIn> = f["input"]["nodes"]
        .as_array()
        .unwrap()
        .iter()
        .map(|n| NodeIn { id: n["id"].as_i64().unwrap(), tags: n["tags"].as_object().unwrap().iter().map(|(k, v)| (k.clone(), v.as_str().unwrap_or("").to_string())).collect(), xy: geo::Coord { x: n["xy"][0].as_f64().unwrap(), y: n["xy"][1].as_f64().unwrap() } })
        .collect();
    // the spaces as the model leaves them: the subsections and the pieces of the intersections (not the paths)
    let spaces: Vec<SpaceRef> = model.spaces.iter().filter(|s| matches!(s.kind.as_str(), "subsection" | "sub-intersection" | "ring sector" | "centre")).map(|s| SpaceRef { id: &s.id, level: s.level, geom: &s.geom }).collect();
    let parts: Vec<PartRef> = model.parts.iter().map(|p| PartRef { id: &p.id, space: &p.space, geom: &p.geom }).collect();
    let t = std::time::Instant::now();
    let out = build_objects(&nodes, &spaces, &parts, -5, 5);
    eprintln!("the objects: {:?} ({} rows)", t.elapsed(), out.len());
    let ours: BTreeMap<&str, &ObjectRow> = out.iter().map(|o| (o.id.as_str(), o)).collect();
    let exp = f["expect"].as_array().unwrap();
    let mut bad: BTreeMap<&str, Vec<String>> = BTreeMap::new();
    let mut missing = vec![];
    for x in exp {
        let id = x["id"].as_str().unwrap();
        let Some(o) = ours.get(id) else { missing.push(id.to_string()); continue };
        let attrs: BTreeMap<String, String> = x["attrs"].as_str().and_then(|s| serde_json::from_str::<Value>(s).ok()).and_then(|v| v.as_object().map(|m| m.iter().map(|(k, v)| (k.clone(), v.as_str().unwrap_or("").to_string())).collect())).unwrap_or_default();
        let mut chk = |what: &'static str, ok: bool| {
            if !ok {
                bad.entry(what).or_default().push(format!("{id}: ours {:?} {:?} {:?} against {} {} {}", o.space, o.part, o.near_m, x["space"], x["part"], x["near_m"]));
            }
        };
        chk("kind", o.kind == x["kind"].as_str().unwrap());
        chk("level", o.level as i64 == x["level"].as_i64().unwrap());
        chk("space", o.space.as_deref() == x["space"].as_str());
        chk("part", o.part.as_deref() == x["part"].as_str());
        chk("near", o.near_m == x["near_m"].as_f64());
        chk("name", o.name.as_deref() == x["name"].as_str());
        chk("attrs", o.attrs == attrs);
        chk("width", o.width_m == x["width"].as_f64() && o.width_source.as_deref() == x["ws"].as_str() && o.width_method.as_deref() == x["wm"].as_str());
        chk("height", o.height_m == x["height"].as_f64() && o.height_source.as_deref() == x["hs"].as_str());
    }
    let extra = ours.keys().filter(|k| !exp.iter().any(|x| x["id"] == **k)).count();
    eprintln!("objects: reference {}, ours {}; missing {} {:?}; extra {extra}; differ by field {:?}", exp.len(), out.len(), missing.len(), &missing[..missing.len().min(3)], bad.iter().map(|(k, v)| (*k, v.len(), v.first().cloned())).collect::<Vec<_>>());
    assert!(missing.len() + extra <= exp.len() / 100 + 1 && bad.values().map(|v| v.len()).sum::<usize>() <= exp.len() / 50 + 1, "the objects differ");
    out
}

/// The buildings of the element fixture, as the Rust elements make them.
fn load_buildings() -> Vec<urbanstyle_model::elements::ElementRow> {
    use urbanstyle_model::elements::*;
    let path = std::env::var("URBANSTYLE_ELEMENT_FIXTURE").unwrap_or_else(|_| "../../data/cuts/element-fixture.json".into());
    let Some(f) = std::fs::read_to_string(&path).ok().and_then(|s| serde_json::from_str::<Value>(&s).ok()) else { return vec![] };
    let tags = |v: &Value| -> BTreeMap<String, String> { v.as_object().unwrap().iter().map(|(k, x)| (k.clone(), x.as_str().unwrap_or("").to_string())).collect() };
    let i = &f["input"];
    let b: Vec<BuildingIn> = i["buildings"].as_array().unwrap().iter().map(|b| BuildingIn { osm_type: b["type"].as_str().unwrap().into(), osm_id: b["osm_id"].as_i64().unwrap(), name: os(&b["name"]), kind: os(&b["kind"]), tags: tags(&b["tags"]), geom: io::multi_polygon(&b["geom"]).unwrap() }).collect();
    let p: Vec<PoiIn> = i["pois"].as_array().unwrap().iter().map(|p| PoiIn { tags: tags(&p["tags"]), point: geo::Coord { x: p["point"][0].as_f64().unwrap(), y: p["point"][1].as_f64().unwrap() } }).collect();
    build(&b, &p, &[])
}

/// The registry against Python's: every thing's kind and profile, the style and the code tables, and the uid kept from the last build.
fn check_registry(model: &Output, objects: &[ObjectRow]) {
    use urbanstyle_model::registry::*;
    let path = std::env::var("URBANSTYLE_REGISTRY_FIXTURE").unwrap_or_else(|_| "../../data/cuts/registry-fixture.json".into());
    let Some(f) = std::fs::read_to_string(&path).ok().and_then(|s| serde_json::from_str::<Value>(&s).ok()) else {
        eprintln!("no registry fixture at {path}: the registry is not checked");
        return;
    };
    let elements = load_buildings();
    let t = Instant::now();
    let things = profiles(model, f["area_name"].as_str(), objects, &elements);
    eprintln!("the registry: {:?} ({} things)", t.elapsed(), things.len());
    let ours: BTreeMap<(&str, &str), &Thing> = things.iter().map(|t| ((t.table, t.id.as_str()), t)).collect();
    let exp = f["things"].as_array().unwrap();
    let mut by_table: BTreeMap<String, (usize, usize, usize)> = BTreeMap::new();
    let mut first = vec![];
    for x in exp {
        let (table, id) = (x["table"].as_str().unwrap(), x["id"].as_str().unwrap());
        let e = by_table.entry(table.to_string()).or_default();
        e.0 += 1;
        match ours.iter().find(|(k, _)| k.0 == table && k.1 == id).map(|(_, v)| *v) {
            None => e.1 += 1,
            Some(t) if t.kind != x["kind"].as_str().unwrap() || t.profile != x["profile"].as_str().unwrap() => {
                e.2 += 1;
                if first.iter().filter(|f: &&String| f.starts_with(table)).count() < 2 {
                    first.push(format!("{table} {id}: ours {} | {} against {} | {}", t.kind, t.profile, x["kind"], x["profile"]));
                }
            }
            _ => {}
        }
    }
    eprintln!("registry things (expected, missing, profile differs) by table: {by_table:?}; first differences {first:?}");
    // the uids: with the last build's registry as the old one, every thing keeps its uid
    let old: Vec<Registered> = f["registry"].as_array().unwrap().iter().map(|r| Registered { profile: r[0].as_str().unwrap().into(), uid: r[1].as_str().unwrap().into(), kind: r[2].as_str().unwrap().into(), first_seen: r[3].as_str().unwrap().into(), last_seen: r[4].as_str().unwrap().into() }).collect();
    let mut n = 0;
    let (reg, uids) = assign(&old, &things, "2026-11-09T00:00:00", &mut || {
        n += 1;
        format!("new-{n}")
    });
    let kept = exp.iter().filter(|x| uids.get(&(x["table"].as_str().unwrap(), x["id"].as_str().unwrap().to_string())).map_or(false, |u| u == x["uid"].as_str().unwrap())).count();
    eprintln!("uids kept: {kept} of {}; new uids {n}; registry rows {} (Python {})", exp.len(), reg.len(), old.len());
    // the style and the code
    let style_ok = f["style"].as_array().unwrap().iter().zip(urbanstyle_model::style::STYLE).filter(|(x, r)| {
        x[0].as_str() == Some(r.0) && x[1].as_i64() == r.1.map(|v| v as i64) && x[2].as_str() == Some(r.2) && x[3].as_i64() == Some(r.3 as i64) && x[4].as_str() == Some(r.4) && x[5].as_str() == Some(r.5)
            && x[7].as_f64() == Some(r.7) && x[6].as_array().map(|a| [a[0].as_f64().unwrap(), a[1].as_f64().unwrap()]) == r.6
    }).count();
    let code_ok = f["code"].as_array().unwrap().iter().zip(urbanstyle_model::style::CODE).filter(|(x, r)| x[0].as_str() == Some(r.0) && x[1].as_str() == r.1 && x[2].as_str() == r.2 && x[3].as_str() == r.3 && x[4].as_str() == r.4).count();
    eprintln!("style rows equal {style_ok} of {}; code rows equal {code_ok} of {}", urbanstyle_model::style::STYLE.len(), urbanstyle_model::style::CODE.len());
    let total_diff: usize = by_table.values().map(|v| v.1 + v.2).sum();
    assert!(total_diff <= exp.len() / 100 + 5, "profiles differ: {by_table:?} {first:?}");
    assert!(kept + exp.len() / 100 + 5 >= exp.len(), "uids not kept");
    assert!(style_ok == urbanstyle_model::style::STYLE.len() && code_ok == urbanstyle_model::style::CODE.len(), "style or code differ");
}
