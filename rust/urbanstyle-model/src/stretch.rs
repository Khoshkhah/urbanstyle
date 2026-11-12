//! Rank 2 of the model: the stretches (the sections with their subsections chained, the intersections, the path sections and path
//! intersections), the arms (each section that arrives at an intersection) and the named streets (`product.write`, "rank 2").
use crate::rank1::Best;
use crate::{Input, SectionInfo};
use geo::{Centroid, Coord, Distance, Euclidean, LineString, Point};
use std::collections::{BTreeMap, BTreeSet, HashMap};
use urbanstyle_geo::index::SegIndex;
use urbanstyle_geo::lines;
use urbanstyle_geo::ops::{self, Mp};

/// An intersection is at a section's end when it lies this near the end of the section's axis.
pub const END_M: f64 = 15.0;
/// A roundabout: a ring line that runs this far inside the intersection.
pub const RING_M: f64 = 5.0;

pub struct StretchRow {
    pub id: String,
    pub kind: String,
    pub parent: Option<String>,
    pub level: i32,
    pub name: Option<String>,
    pub street: Option<String>,
    pub ways: Vec<String>,
    pub nodes: Vec<i64>,
    pub class: Option<String>,
    pub oneway: Option<bool>,
    pub length: Option<f64>,
    pub axis: Option<LineString<f64>>,
    pub r#ref: String,
    pub geom: Mp,
}

pub struct ArmRow {
    pub intersection: String,
    pub street: Option<String>,
    pub section: String,
    pub way: Option<String>,
    pub level: i32,
}

pub struct StreetRow {
    pub id: String,
    pub name: Option<String>,
    pub level: i32,
    pub sections: Vec<String>,
    pub intersections: Vec<String>,
    pub geom: Mp,
}

/// What a section knows about its ends, for the links of slice 3.
pub struct SectionEnds {
    pub section: String,
    pub ends: [Option<String>; 2],
}

/// The way in a section's name: `s<level>-w<way>` gives `w<way>`.
pub fn naming(sec: &str) -> Option<String> {
    let b = sec.strip_prefix('s')?;
    let b = b.strip_prefix('-').unwrap_or(b);
    let digits = b.bytes().take_while(|c| c.is_ascii_digit()).count();
    let rest = b[digits..].strip_prefix("-w")?;
    let n = rest.bytes().take_while(|c| c.is_ascii_digit()).count();
    (digits > 0 && n > 0).then(|| format!("w{}", &rest[..n]))
}

/// Every `w<digits>` that starts a word in the text (`re.findall(r"\bw(\d+)")`).
pub fn ways_in(text: &str) -> Vec<String> {
    let b = text.as_bytes();
    let mut out = Vec::new();
    let mut i = 0;
    while i < b.len() {
        let word_start = i == 0 || !(b[i - 1].is_ascii_alphanumeric() || b[i - 1] == b'_');
        if b[i] == b'w' && word_start {
            let n = b[i + 1..].iter().take_while(|c| c.is_ascii_digit()).count();
            if n > 0 {
                out.push(text[i..i + 1 + n].to_string());
                i += 1 + n;
                continue;
            }
        }
        i += 1;
    }
    out
}

pub(crate) fn common<T: Clone + PartialEq>(xs: &[T]) -> Option<T> {
    let mut best: Option<(usize, &T)> = None;
    for x in xs {
        let n = xs.iter().filter(|y| *y == x).count();
        if best.map_or(true, |b| n > b.0) {
            best = Some((n, x));
        }
    }
    best.map(|b| b.1.clone())
}

pub fn build(inp: &Input, sections: &[SectionInfo], street_best: &BTreeMap<i32, Best>) -> (Vec<StretchRow>, Vec<ArmRow>, Vec<StreetRow>, Vec<SectionEnds>) {
    let mut lap = urbanstyle_geo::Lap::new("model stretches");
    let units: HashMap<&str, &crate::Unit> = inp.units.iter().map(|u| (u.id.as_str(), u)).collect();
    let mut parts_of: HashMap<&str, Vec<&crate::Part>> = HashMap::new();
    for p in &inp.parts {
        parts_of.entry(p.unit.as_str()).or_default().push(p);
    }
    // the ways each space's parts name, with the middle of the part; and the roads of its lanes
    let ways_of = |u: &str| -> Vec<(Coord<f64>, String)> {
        parts_of.get(u).map_or(vec![], |ps| {
            ps.iter()
                .flat_map(|p| {
                    let c = p.geom.centroid().map_or(Coord { x: 0.0, y: 0.0 }, |c| c.0);
                    ways_in(p.r#ref.as_deref().unwrap_or("")).into_iter().map(move |w| (c, w))
                })
                .collect()
        })
    };
    let roads_of = |u: &str| -> Vec<String> { parts_of.get(u).map_or(vec![], |ps| ps.iter().filter(|p| p.typ == "lane").filter_map(|p| p.road.clone()).filter(|r| !r.is_empty()).collect()) };
    let inters: Vec<&crate::Unit> = inp.units.iter().filter(|u| u.kind == "intersection").collect();
    let inter_index = urbanstyle_geo::index::Index::new(inters.iter().map(|i| geo::BoundingRect::bounding_rect(&i.geom)));
    let mut jnodes: HashMap<&str, Vec<i64>> = HashMap::new();
    for j in &inp.junctions {
        jnodes.entry(j.intersection.as_str()).or_default().push(j.node);
    }
    let dist = |m: &Mp, c: Coord<f64>| Euclidean.distance(m, &Point::from(c));

    let mut rows: Vec<StretchRow> = Vec::new();
    let mut ends_out = Vec::new();
    struct Sec {
        id: String,
        level: i32,
        street: Option<String>,
        name: Option<String>,
        ends: [Option<String>; 2],
        geom: Mp,
    }
    let mut secs: Vec<Sec> = Vec::new();
    for sd in sections {
        // the ways, in the order along the axis, space by space
        let mut ways: Vec<String> = Vec::new();
        for s in &sd.ids {
            let mut ws = ways_of(s);
            if let Some(ax) = &sd.axis {
                // (each key once: a sort compares each one many times)
                let mut keyed: Vec<(f64, (Coord<f64>, String))> = ws.into_iter().map(|w| (lines::project(ax, w.0), w)).collect();
                keyed.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap());
                ws = keyed.into_iter().map(|x| x.1).collect();
            }
            for (_, w) in ws {
                if !ways.contains(&w) {
                    ways.push(w);
                }
            }
        }
        let nm_way = naming(&sd.id);
        if ways.is_empty() {
            if let Some(w) = &nm_way {
                ways = vec![w.clone()];
            }
        }
        let roads: Vec<String> = sd.ids.iter().flat_map(|s| roads_of(s)).collect();
        let name = common(&roads);
        let geom = ops::union_all(sd.ids.iter().filter_map(|s| units.get(s.as_str())).map(|u| &u.geom).collect::<Vec<_>>().into_iter());
        let mut ends: [Option<String>; 2] = [None, None];
        let mut nodes: Vec<Option<i64>> = vec![None, None];
        if let Some(ax) = &sd.axis {
            for (e, pt) in [ax.0[0], *ax.0.last().unwrap()].into_iter().enumerate() {
                // (only the intersections whose box lies within END_M of the end can be nearer than END_M)
                let around = geo::Rect::new(Coord { x: pt.x - END_M, y: pt.y - END_M }, Coord { x: pt.x + END_M, y: pt.y + END_M });
                let near = inter_index.query(&around).into_iter().map(|k| inters[k]).filter(|i| i.level == sd.level).map(|i| (dist(&i.geom, pt), i.id.as_str())).filter(|x| x.0 < END_M).min_by(|a, b| a.partial_cmp(b).unwrap());
                ends[e] = near.map(|x| x.1.to_string());
                if let Some(i_) = &ends[e] {
                    let cand = jnodes.get(i_.as_str()).map(|v| v.iter().filter(|n| inp.node_pt.contains_key(n)).copied().collect::<Vec<_>>()).unwrap_or_default();
                    nodes[e] = cand.into_iter().min_by(|a, b| {
                        let d = |n: &i64| (inp.node_pt[n].x - pt.x).hypot(inp.node_pt[n].y - pt.y);
                        d(a).partial_cmp(&d(b)).unwrap()
                    });
                }
            }
        }
        let street = nm_way.as_ref().and_then(|w| inp.way_street.get(w)).cloned().or_else(|| name.as_ref().and_then(|n| inp.name_street.get(&(n.clone(), sd.level))).cloned());
        let cls = common(&sd.classes);
        let oneway = sd.oneways.iter().all(|o| *o);
        let length = sd.axis.as_ref().map(lines::length);
        let parent = street_best.get(&sd.level).and_then(|b| b.of(&geom));
        rows.push(StretchRow {
            id: sd.id.clone(),
            kind: "section".into(),
            parent,
            level: sd.level,
            name: name.clone(),
            street: street.clone(),
            r#ref: ways.join(","),
            ways,
            nodes: nodes.iter().flatten().copied().collect(),
            class: cls,
            oneway: Some(oneway),
            length,
            axis: sd.axis.clone(),
            geom: geom.clone(),
        });
        ends_out.push(SectionEnds { section: sd.id.clone(), ends: ends.clone() });
        secs.push(Sec { id: sd.id.clone(), level: sd.level, street, name, ends, geom });
    }

    lap.lap("sections");
    // the intersections
    for i_ in &inters {
        let idx = SegIndex::new(&i_.geom);
        let round = inp.roundabouts.iter().any(|ln| idx.clip_line(ln, true).iter().map(lines::length).sum::<f64>() > RING_M);
        let mut ways: Vec<String> = Vec::new();
        for (_, w) in ways_of(&i_.id) {
            if !ways.contains(&w) {
                ways.push(w);
            }
        }
        let mut roads = roads_of(&i_.id);
        roads.sort();
        roads.dedup();
        let mut nodes = jnodes.get(i_.id.as_str()).cloned().unwrap_or_default();
        nodes.sort();
        rows.push(StretchRow {
            id: i_.id.clone(),
            kind: if round { "roundabout" } else { "intersection" }.into(),
            parent: street_best.get(&i_.level).and_then(|b| b.of(&i_.geom)),
            level: i_.level,
            name: (!roads.is_empty()).then(|| roads.join(" / ")),
            street: None,
            r#ref: ways.join(","),
            ways,
            nodes,
            class: None,
            oneway: None,
            length: None,
            axis: None,
            geom: i_.geom.clone(),
        });
    }
    for x in &inp.path_spaces {
        rows.push(StretchRow {
            id: x.id.clone(),
            kind: x.kind.clone(),
            parent: Some(x.ground.clone()),
            level: x.level,
            name: x.name.clone(),
            street: None,
            ways: x.ways.clone(),
            nodes: x.nodes.clone(),
            class: x.class.clone(),
            oneway: if x.kind == "path section" { Some(false) } else { None },
            length: x.length,
            axis: x.axis.clone(),
            r#ref: x.ways.join(","),
            geom: x.geom.clone(),
        });
    }

    lap.lap("intersections");
    // the arms and the named streets
    let mut arms = Vec::new();
    for i_ in &inters {
        for sd in &secs {
            if sd.ends.iter().any(|e| e.as_deref() == Some(i_.id.as_str())) {
                arms.push(ArmRow { intersection: i_.id.clone(), street: sd.street.clone(), section: sd.id.clone(), way: naming(&sd.id), level: i_.level });
            }
        }
    }
    struct St {
        level: i32,
        sections: Vec<usize>,
        inters: BTreeSet<String>,
        names: Vec<String>,
    }
    let mut streets: BTreeMap<String, St> = BTreeMap::new();
    for (k, sd) in secs.iter().enumerate() {
        if let Some(sid) = &sd.street {
            let e = streets.entry(sid.clone()).or_insert(St { level: sd.level, sections: vec![], inters: BTreeSet::new(), names: vec![] });
            e.sections.push(k);
            e.inters.extend(sd.ends.iter().flatten().cloned());
            if let Some(n) = &sd.name {
                e.names.push(n.clone());
            }
        }
    }
    let inter_geom: HashMap<&str, &Mp> = inters.iter().map(|i| (i.id.as_str(), &i.geom)).collect();
    let street_rows = streets
        .into_iter()
        .map(|(k, v)| {
            let mut sections: Vec<String> = v.sections.iter().map(|&i| secs[i].id.clone()).collect();
            sections.sort();
            let geoms: Vec<&Mp> = v.sections.iter().map(|&i| &secs[i].geom).chain(v.inters.iter().filter_map(|i| inter_geom.get(i.as_str()).copied())).collect();
            StreetRow { id: k, name: common(&v.names), level: v.level, sections, intersections: v.inters.into_iter().collect(), geom: ops::union_all(geoms.into_iter()) }
        })
        .collect();
    lap.lap("arms and streets");
    (rows, arms, street_rows, ends_out)
}
