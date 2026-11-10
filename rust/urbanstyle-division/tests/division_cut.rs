//! The Rust division against the Python reference (simready.py) on a cut: the same inputs, the same rules. The data is made by
//! rust/tools/export_division_fixture.py and is not in git: with no file the test says so and passes.
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet};
use std::time::Instant;
use urbanstyle_division::*;
use urbanstyle_geo::io;
use urbanstyle_geo::ops::{self, Mp};

fn fixture() -> Option<Value> {
    let path = std::env::var("URBANSTYLE_DIVISION_FIXTURE").unwrap_or_else(|_| "../../data/cuts/division-fixture.json".into());
    match std::fs::read_to_string(&path) {
        Ok(s) => serde_json::from_str(&s).ok(),
        Err(_) => {
            eprintln!("no fixture at {path}: run rust/tools/export_division_fixture.py; test skipped");
            None
        }
    }
}

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

fn input(f: &Value) -> Input {
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

#[test]
fn the_constants_are_the_python_ones() {
    let Some(f) = fixture() else { return };
    let c = &f["consts"];
    let eq = |k: &str, v: f64| assert!((c[k].as_f64().unwrap() - v).abs() < 1e-12, "{k}");
    eq("cut_m", CUT_M);
    eq("clear_m", CLEAR_M);
    eq("furnish_m", FURNISH_M);
    eq("crosswalk_m", CROSSWALK_M);
    eq("zebra_bar_m", ZEBRA_BAR_M);
    eq("zebra_gap_m", ZEBRA_GAP_M);
    eq("xwalk_max_m", XWALK_MAX_M);
    eq("edge_touch_m", EDGE_TOUCH_M);
}

#[test]
fn spaces_parts_and_marks_agree_with_the_python_reference() {
    let Some(f) = fixture() else { return };
    let inp = input(&f);
    let t = Instant::now();
    let out = build(&inp);
    eprintln!("the division: {:?} ({} spaces, {} crosswalks, {} turns, {} approaches)", t.elapsed(), out.units.len(), out.crosswalks, out.turns, out.approaches);
    let e = &f["expect"];

    // the spaces
    let exp_units: BTreeSet<String> = e["units"].as_array().unwrap().iter().map(|u| s(&u["id"])).collect();
    let our_units: BTreeSet<String> = out.units.iter().map(|u| u.id.clone()).collect();
    let (missing, extra): (Vec<_>, Vec<_>) = (exp_units.difference(&our_units).cloned().collect(), our_units.difference(&exp_units).cloned().collect());
    eprintln!("spaces: reference {}, ours {}; missing {:?}; extra {:?}", exp_units.len(), our_units.len(), missing, extra);

    // the parts: the area of each type, in all and by space
    let mut by_type: BTreeMap<String, (f64, f64, usize, usize)> = BTreeMap::new(); // type -> (reference area, our area, reference count, our count)
    let mut ours: BTreeMap<String, (usize, f64)> = BTreeMap::new();
    for u in &out.units {
        for p in &u.parts {
            let a = ours.entry(format!("{}|{}", u.id, p.typ)).or_insert((0, 0.0));
            a.0 += 1;
            a.1 += ops::area(&p.geom);
        }
    }
    let exp_parts: BTreeMap<String, (usize, f64)> = e["parts"].as_object().unwrap().iter().map(|(k, v)| (k.clone(), (v[0].as_u64().unwrap() as usize, v[1].as_f64().unwrap()))).collect();
    for (k, (n, a)) in &exp_parts {
        let t = k.split('|').nth(1).unwrap().to_string();
        let x = by_type.entry(t).or_insert((0.0, 0.0, 0, 0));
        x.0 += a;
        x.2 += n;
    }
    for (k, (n, a)) in &ours {
        let t = k.split('|').nth(1).unwrap().to_string();
        let x = by_type.entry(t).or_insert((0.0, 0.0, 0, 0));
        x.1 += a;
        x.3 += n;
    }
    for (t, (ra, oa, rn, on)) in &by_type {
        eprintln!("  parts {t:14}: area {oa:10.0} against {ra:10.0} m2 ({:+.2}%), count {on} against {rn}", 100.0 * (oa - ra) / ra.max(1e-9));
    }
    let off: Vec<_> = exp_parts
        .iter()
        .filter(|(k, (_, a))| ours.get(*k).map_or(true, |(_, oa)| (oa - a).abs() > (0.01 * a).max(1.0)))
        .map(|(k, (_, a))| (k.clone(), *a, ours.get(k).map(|x| x.1)))
        .collect();
    eprintln!("space-and-type groups of the reference whose area is off by more than 1% or 1 m2: {} of {}; the first: {:?}", off.len(), exp_parts.len(), &off.iter().map(|(k, a, o)| format!("{k} ref {a:.0} ours {}", o.map_or("-".to_string(), |x| format!("{x:.0}")))).collect::<Vec<_>>());

    let mut isl: Vec<(f64, String)> = exp_parts.iter().filter(|(k, _)| k.ends_with("|island")).map(|(k, (n, a))| (ours.get(k).map_or(0.0, |x| x.1) - a, format!("{k} ref {a:.0} ({n}) ours {:.0} ({})", ours.get(k).map_or(0.0, |x| x.1), ours.get(k).map_or(0, |x| x.0)))).collect();
    for (k, (n, a)) in &ours { if k.ends_with("|island") && !exp_parts.contains_key(k) { isl.push((*a, format!("{k} ref none ours {a:.0} ({n})"))); } }
    isl.sort_by(|a, b| b.0.abs().partial_cmp(&a.0.abs()).unwrap());
    eprintln!("island differences: {:#?}", isl.iter().take(8).map(|x| &x.1).collect::<Vec<_>>());
    // the marks
    let mut our_marks: BTreeMap<String, (usize, f64)> = BTreeMap::new();
    for u in &out.units {
        for m in &u.marks {
            let a = our_marks.entry(format!("{}|{}", u.id, m.typ)).or_insert((0, 0.0));
            a.0 += 1;
            a.1 += lines_len(&m.line);
        }
    }
    let exp_marks: BTreeMap<String, (usize, f64)> = e["marks"].as_object().unwrap().iter().map(|(k, v)| (k.clone(), (v[0].as_u64().unwrap() as usize, v[1].as_f64().unwrap()))).collect();
    let mut mt: BTreeMap<String, (f64, f64, usize, usize)> = BTreeMap::new();
    for (k, (n, l)) in &exp_marks {
        let x = mt.entry(k.split('|').nth(1).unwrap().to_string()).or_insert((0.0, 0.0, 0, 0));
        x.0 += l;
        x.2 += n;
    }
    for (k, (n, l)) in &our_marks {
        let x = mt.entry(k.split('|').nth(1).unwrap().to_string()).or_insert((0.0, 0.0, 0, 0));
        x.1 += l;
        x.3 += n;
    }
    for (t, (rl, ol, rn, on)) in &mt {
        eprintln!("  marks {t:14}: length {ol:9.0} against {rl:9.0} m ({:+.2}%), count {on} against {rn}", 100.0 * (ol - rl) / rl.max(1e-9));
    }

    let mut kd: Vec<(f64, String, f64, f64)> = exp_marks
        .iter()
        .filter(|(k, _)| k.ends_with("|kerb"))
        .map(|(k, (_, l))| (our_marks.get(k).map_or(0.0, |x| x.1) - l, k.clone(), *l, our_marks.get(k).map_or(0.0, |x| x.1)))
        .collect();
    kd.sort_by(|a, b| b.0.abs().partial_cmp(&a.0.abs()).unwrap());
    eprintln!("kerb: the units with the largest difference: {:?}", kd.iter().take(6).map(|x| format!("{} ref {:.0} ours {:.0}", x.1, x.2, x.3)).collect::<Vec<_>>());
    // the rows
    let exp_j: BTreeSet<(String, i64)> = e["junctions"].as_array().unwrap().iter().map(|r| (s(&r[0]), r[1].as_i64().unwrap())).collect();
    let our_j: BTreeSet<(String, i64)> = out.junction_rows.iter().map(|r| (r.0.clone(), r.1)).collect();
    eprintln!("junction rows: reference {}, ours {}; turns {} against {}; approaches {} against {}", exp_j.len(), our_j.len(), out.turns, e["turns"], out.approaches, e["approaches"]);
    let mut sub_off = 0;
    for sub in e["subsections"].as_array().unwrap() {
        let id = s(&sub["id"]);
        let (Some(u), Some(len)) = (out.units.iter().find(|u| u.id == id), sub["length"].as_f64()) else { continue };
        if u.axis.as_ref().map_or(true, |a| (lines_len(a) - len).abs() > 0.2) {
            sub_off += 1;
        }
    }
    eprintln!("subsection lengths off by more than 0.2 m: {sub_off} of {}", e["subsections"].as_array().unwrap().len());

    assert!(missing.is_empty() && extra.is_empty(), "the spaces differ");
    // the parts: the area of each type to 0.5%; the types that depend on who owns a piece of the walking side (the Python overlays snap to
    // 1 cm, so two units that touch a piece for nearly the same length can swap it) to 3%; the others also agree in count
    for (t, (ra, oa, rn, on)) in &by_type {
        let tol = if ["frontage", "furnishing", "sidewalk", "island"].contains(&t.as_str()) { 0.03 } else { 0.005 };
        assert!((oa - ra).abs() <= tol * ra.max(1.0), "parts {t}: area {oa} against {ra}");
        if ["lane", "junction area", "crosswalk", "bus lane", "cycle lane"].contains(&t.as_str()) {
            assert_eq!(on, rn, "parts {t}: count");
        }
    }
    // the marks: the lines of the roadway to 0.1%; the kerb, which follows the owner of each piece, to 5%
    for (t, (rl, ol, _, _)) in &mt {
        let tol = if t == "kerb" { 0.05 } else { 0.001 };
        assert!((ol - rl).abs() <= tol * rl.max(1.0), "marks {t}: length {ol} against {rl}");
    }
    assert_eq!(our_j, exp_j, "the junction rows differ");
    assert_eq!(out.turns as u64, e["turns"].as_u64().unwrap(), "turns");
    assert_eq!(out.approaches as u64, e["approaches"].as_u64().unwrap(), "approaches");
}

fn lines_len(l: &geo::LineString<f64>) -> f64 {
    urbanstyle_geo::lines::length(l)
}

/// Not a check: the parts and marks of one space (URBANSTYLE_UNIT=id).
#[test]
fn one_space() {
    let (Some(f), Ok(id)) = (fixture(), std::env::var("URBANSTYLE_UNIT")) else { return };
    let out = build(&input(&f));
    let Some(u) = out.units.iter().find(|u| u.id == id) else { return eprintln!("no space {id}") };
    let mut parts: BTreeMap<&str, (usize, f64)> = BTreeMap::new();
    for p in &u.parts {
        let x = parts.entry(&p.typ).or_insert((0, 0.0));
        x.0 += 1;
        x.1 += ops::area(&p.geom);
    }
    let mut marks: BTreeMap<&str, (usize, f64)> = BTreeMap::new();
    for m in &u.marks {
        let x = marks.entry(&m.typ).or_insert((0, 0.0));
        x.0 += 1;
        x.1 += lines_len(&m.line);
    }
    eprintln!("{id}: parts {parts:?}; marks {marks:?}");
}
