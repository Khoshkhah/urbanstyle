//! The data about the data (docs/design/tables.md): the registry of stable ids `urban.registry` and the `uid` of each thing in it, the
//! manifest `urban.meta`, the style and the codes. The port of `meta.py`.
//!
//! A thing's profile is its facts that do not change from build to build, as text (a street piece: the names of its sections; a lane: its
//! side, its direction and its number). A thing that has the same profile in the next build keeps its uid; a new profile gets a new one.
use crate::elements::ElementRow;
use crate::objects::ObjectRow;
use crate::Output;
use std::collections::{BTreeMap, BTreeSet};

/// A thing of the model: its registry kind, its table, its id and its profile.
#[derive(Clone, Debug, PartialEq)]
pub struct Thing {
    pub kind: String,
    pub table: &'static str,
    pub id: String,
    pub profile: String,
}

/// One row of `urban.registry`.
#[derive(Clone, Debug, PartialEq)]
pub struct Registered {
    pub profile: String,
    pub uid: String,
    pub kind: String,
    pub first_seen: String,
    pub last_seen: String,
}

/// `"|".join(sorted({x for x in xs if x}))`.
fn names<'a>(xs: impl IntoIterator<Item = Option<&'a str>>) -> String {
    xs.into_iter().flatten().filter(|x| !x.is_empty()).collect::<BTreeSet<&str>>().into_iter().collect::<Vec<_>>().join("|")
}

fn py_opt<T: std::fmt::Display>(x: &Option<T>) -> String {
    x.as_ref().map_or("None".to_string(), |v| v.to_string())
}

/// The profile of every thing of the model (`meta.profiles`). Two things of one kind and table with one profile get `#2`, `#3`, ... in the
/// order of their ids.
pub fn profiles(out: &Output, area_name: Option<&str>, objects: &[ObjectRow], elements: &[ElementRow]) -> Vec<Thing> {
    let mut things: Vec<(String, &'static str, String, String)> = Vec::new();
    for lv in &out.levels {
        things.push(("area".into(), "area", format!("a{lv}"), format!("area:{}:{lv}", area_name.unwrap_or("None"))));
    }
    // ground: the street pieces by the names of their sections, the plots by the names of their sides, the others by their OSM way
    let mut secnames: BTreeMap<&str, Vec<Option<&str>>> = BTreeMap::new();
    for s in out.stretches.iter().filter(|s| s.kind == "section") {
        if let Some(p) = &s.parent {
            secnames.entry(p.as_str()).or_default().push(s.name.as_deref());
        }
    }
    let mut ground: BTreeMap<&str, String> = BTreeMap::new();
    for g in &out.ground {
        let p = match g.kind.as_str() {
            "street" => format!("street:{}:{}", g.level, names(secnames.get(g.id.as_str()).cloned().unwrap_or_default())),
            "plot" => format!("plot:{}:{}", g.level, names(g.sides.iter().flatten().map(|s| s.name.as_deref()))),
            _ => match &g.r#ref {
                Some(r) if !r.is_empty() => format!("osm:{}", r.split_once('-').map_or(r.as_str(), |x| x.1).split('.').next().unwrap()),
                _ => format!("path:{}", g.id),
            },
        };
        things.push((g.kind.clone(), "ground", g.id.clone(), p.clone()));
        ground.insert(g.id.as_str(), p);
    }
    // stretch: an intersection by the names of its roads; a section by its name and the profiles of the intersections it ends at
    let mut stretch: BTreeMap<&str, String> = BTreeMap::new();
    for s in out.stretches.iter().filter(|s| s.kind != "section") {
        let p = match s.kind.as_str() {
            "intersection" | "roundabout" => format!("intersection:{}:{}", s.level, names(s.name.as_deref().unwrap_or("").split(" / ").map(Some))),
            "path section" if !s.ways.is_empty() => format!("osm:{}", s.ways[0]),
            "path intersection" => format!("osm:n{}", s.id.split_once('-').map_or("", |x| x.1).split('.').next().unwrap()),
            k => format!("{k}:{}", s.id),
        };
        stretch.insert(s.id.as_str(), p);
    }
    let mut ends: BTreeMap<&str, Vec<String>> = BTreeMap::new();
    for a in &out.arms {
        ends.entry(a.section.as_str()).or_default().push(stretch.get(a.intersection.as_str()).cloned().unwrap_or_else(|| a.intersection.clone()));
    }
    for s in out.stretches.iter().filter(|s| s.kind == "section") {
        let mut e = ends.get(s.id.as_str()).cloned().unwrap_or_default();
        e.sort();
        stretch.insert(s.id.as_str(), format!("section:{}:{}:{}", s.level, s.name.as_deref().unwrap_or(""), e.join("+")));
    }
    for s in &out.stretches {
        things.push((s.kind.clone(), "stretch", s.id.clone(), stretch[s.id.as_str()].clone()));
    }
    for p in &out.plot_pieces {
        let mapped = p.source.as_deref().map_or(false, |s| s != "urbanstyle")
            && p.r#ref.as_deref().map_or(false, |r| r.starts_with(['w', 'n', 'r']) && r[1..].split('/').next().map_or(false, |d| !d.is_empty() && d.bytes().all(|b| b.is_ascii_digit())));
        let prof = if mapped {
            format!("{}:{}", p.source.as_deref().unwrap().split('+').next().unwrap(), p.r#ref.as_deref().unwrap().split('/').next().unwrap())
        } else {
            let par = p.parent.as_deref().unwrap_or("None");
            format!("{}:{}", ground.get(par).map_or(par, |s| s.as_str()), p.kind)
        };
        things.push(("plot piece".into(), "plot_piece", p.id.clone(), prof));
    }
    let mut space: BTreeMap<&str, String> = BTreeMap::new();
    for s in &out.spaces {
        let par = stretch.get(s.parent.as_str()).map_or(s.parent.as_str(), |x| x.as_str());
        let last = s.id.rsplit_once('/').map_or("", |x| x.1);
        let p = match s.kind.as_str() {
            "subsection" => format!("{par}/{last}"),
            "sub-intersection" | "ring sector" | "centre" => format!("{par}/{}", if s.kind == "centre" { "centre".to_string() } else { format!("osm:n{last}") }),
            _ => stretch.get(s.id.as_str()).cloned().unwrap_or_else(|| s.id.clone()),
        };
        things.push((s.kind.clone(), "space", s.id.clone(), p.clone()));
        space.insert(s.id.as_str(), p);
    }
    let mut side: BTreeMap<&str, String> = BTreeMap::new();
    for s in &out.sides {
        let p = format!("{}:{}", space.get(s.parent.as_str()).map_or(s.parent.as_str(), |x| x.as_str()), s.id.chars().last().unwrap_or(' '));
        things.push(("side".into(), "side", s.id.clone(), p.clone()));
        side.insert(s.id.as_str(), p);
    }
    for p in &out.parts {
        let sd = side.get(p.side.as_str()).map_or(p.side.as_str(), |x| x.as_str());
        let prof = if p.typ == "lane" { format!("{sd}:lane:{}:{}", py_opt(&p.direction), py_opt(&p.lane)) } else { format!("{sd}:{}", p.typ) };
        things.push(("part".into(), "part", p.id.clone(), prof));
    }
    for m in &out.marks {
        things.push(("mark".into(), "mark", m.id.clone(), format!("{}:{}", space.get(m.space.as_str()).map_or(m.space.as_str(), |x| x.as_str()), m.kind)));
    }
    for o in objects {
        things.push(("street object".into(), "object", o.id.clone(), format!("osm:{}", o.id)));
    }
    for e in elements.iter().filter(|e| e.kind == "building") {
        things.push(("building".into(), "element", e.id.clone(), format!("{}:{}", e.source, e.id)));
    }
    // two things of one kind and table with one profile: #2, #3 in the order of their ids
    things.sort_by(|a, b| (&a.0, &a.3, &a.2).cmp(&(&b.0, &b.3, &b.2)));
    let mut seen: BTreeMap<(String, String, &'static str), usize> = BTreeMap::new();
    things
        .into_iter()
        .map(|(kind, table, id, profile)| {
            let n = seen.entry((kind.clone(), profile.clone(), table)).or_insert(0);
            *n += 1;
            Thing { profile: if *n > 1 { format!("{profile}#{n}") } else { profile }, kind, table, id }
        })
        .collect()
}

/// The registry after a build, and the uid of each thing (`meta.write_registry`). `old`: the rows of the last build. Every profile the
/// build has keeps its uid; a new profile gets `new_uid()`. A thing that is both a stretch and a space (an intersection, a path section, a
/// path intersection) has one profile, so one uid. `built`: the time of the build, as text.
pub fn assign(old: &[Registered], things: &[Thing], built: &str, new_uid: &mut dyn FnMut() -> String) -> (Vec<Registered>, BTreeMap<(&'static str, String), String>) {
    let mut reg: Vec<Registered> = old.to_vec();
    let mut index: BTreeMap<(String, String), usize> = reg.iter().enumerate().map(|(i, r)| ((r.kind.clone(), r.profile.clone()), i)).collect();
    let mut uids = BTreeMap::new();
    for t in things {
        let key = (t.kind.clone(), t.profile.clone());
        let i = *index.entry(key).or_insert_with(|| {
            reg.push(Registered { profile: t.profile.clone(), uid: new_uid(), kind: t.kind.clone(), first_seen: built.to_string(), last_seen: built.to_string() });
            reg.len() - 1
        });
        reg[i].last_seen = built.to_string();
        uids.insert((t.table, t.id.clone()), reg[i].uid.clone());
    }
    (reg, uids)
}

/// One row of `urban.meta`: key, kind (`build`, `input`, `chosen`), value, note.
pub type MetaRow = (String, String, String, String);

/// The manifest (`meta.write_meta`): the version and the time of the build, every input file with its date, every chosen value with its
/// name and its comment. The caller gives them: the files and the clock are not the model's.
pub fn meta(version: &str, built: &str, inputs: &[(String, String, String)], chosen: &[(String, f64, String)]) -> Vec<MetaRow> {
    let mut rows: Vec<MetaRow> = vec![
        ("version".into(), "build".into(), version.into(), "urbanstyle's version and the git commit of its source".into()),
        ("built".into(), "build".into(), built.into(), "the time the build ended".into()),
    ];
    rows.extend(inputs.iter().map(|(n, p, day)| (format!("input.{n}"), "input".into(), p.clone(), day.clone())));
    rows.extend(chosen.iter().map(|(k, v, note)| (format!("chosen.{k}"), "chosen".into(), format!("{v:?}"), note.clone())));
    rows
}
