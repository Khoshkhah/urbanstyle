//! The model (docs/design/tables.md): the tables of `urban`, made from the rows of the steps. The port of `product.write` of the Python
//! code, in slices (docs/notes/rust-browser.md, "Step 5"). Slice 1, here: the axes of the subsections, their parts and marks.
//!
//! * a section's subsections are chained into one axis; each subsection's own line, turned to continue the one before, is the axis of its
//!   space, with its range (`s_from`, `s_to`) on the chain
//! * a part or mark has a place (s, t) on its space's axis: s along, t across, left positive
//! * a part under `MIN_PART_M2` joins the part of its side it shares the longest edge with
use geo::{Centroid, Coord, Distance, Euclidean, LineString};
use std::collections::{BTreeMap, BTreeSet, HashSet};
use urbanstyle_geo::index::NearIndex;
use urbanstyle_geo::lines;
use urbanstyle_geo::ops::{self, Mp};

pub mod elements;
pub mod intersect;
pub mod objects;
pub mod registry;
pub mod style;
pub mod rank1;
pub mod stretch;
pub use rank1::{GroundRow, PlotPieceRow};
pub use stretch::{ArmRow, SectionEnds, StreetRow, StretchRow};

/// A part under this joins the part of its side it shares the longest edge with.
pub const MIN_PART_M2: f64 = 2.0;
/// The parts of the walking side (rank 4); every other part is on the driving side.
pub const WALKING: [&str; 13] = ["sidewalk", "furnishing", "frontage", "driveway", "island", "verge", "bus stop", "tree pit", "steps", "ramp", "handrail", "bollard", "open"];
/// The parts of a subsection that have no axis of their own: they cross the space or stand in it.
pub const NO_AXIS: [&str; 6] = ["crosswalk", "cycle crossing", "driveway", "tree pit", "bus stop", "junction area"];
const NEAR_M: f64 = 0.05;
/// Two lanes share a joint or a stop line when their outlines touch along at least this length.
pub const TOUCH_M: f64 = 0.5;
/// A turn's guide line starts in the lane nearest its first point, and ends in the lane nearest its last, within this.
pub const TURN_M: f64 = 1.5;

#[derive(Clone)]
pub struct Unit {
    pub id: String,
    pub kind: String,
    pub level: i32,
    pub geom: Mp,
}

/// A ground item as `work.ground` holds it.
#[derive(Clone)]
pub struct GroundIn {
    pub id: String,
    pub typ: String,
    pub level: i32,
    pub name: Option<String>,
    pub source: Option<String>,
    pub method: Option<String>,
    pub r#ref: Option<String>,
    pub geom: Mp,
}

#[derive(Clone)]
pub struct BlockIn {
    pub id: String,
    pub level: i32,
    pub source: Option<String>,
    pub method: Option<String>,
    pub geom: Mp,
}

#[derive(Clone)]
pub struct BlockSideIn {
    pub block: String,
    pub way: i64,
    pub name: Option<String>,
    pub class: Option<String>,
    pub distance_m: Option<f64>,
    pub basis: Option<String>,
    pub method: Option<String>,
}

#[derive(Clone)]
pub struct CorridorIn {
    pub id: String,
    pub name: Option<String>,
    pub width: Option<f64>,
    pub source: Option<String>,
    pub method: Option<String>,
}

#[derive(Clone)]
pub struct SurfaceIn {
    pub id: String,
    pub ground: String,
}

#[derive(Clone)]
pub struct Subsection {
    pub id: String,
    pub section: String,
    pub level: i32,
    pub line: Option<LineString<f64>>,
    pub width: Option<f64>,
    pub oneway: Option<bool>,
    pub length: Option<f64>,
    pub left_extra: Option<f64>,
    pub class: Option<String>,
}

#[derive(Clone)]
pub struct Part {
    pub id: String,
    pub unit: String,
    pub typ: String,
    pub direction: Option<String>,
    pub lane: Option<i64>,
    pub road: Option<String>,
    pub r#ref: Option<String>,
    /// What the division knows of the part besides its place (all optional: the tests give none of it).
    pub extra: PartExtra,
    pub geom: Mp,
}

/// The columns of a part that the model carries to its table.
#[derive(Clone, Default)]
pub struct PartExtra {
    pub lane_id: Option<String>,
    pub width_m: Option<f64>,
    pub width_source: Option<String>,
    pub width_method: Option<String>,
    pub source: Option<String>,
    pub method: Option<String>,
    pub road_class: Option<String>,
    pub oneway: Option<String>,
}

#[derive(Clone)]
pub struct Mark {
    pub unit: String,
    pub typ: String,
    pub level: i32,
    pub source: Option<String>,
    pub method: Option<String>,
    pub reference: Option<String>,
    pub lines: Vec<LineString<f64>>,
}

/// A move from a lane to a lane inside an intersection (`work.turn`).
#[derive(Clone)]
pub struct TurnIn {
    pub unit: String,
    pub level: i32,
    pub from_edge: Option<String>,
    pub from_lane: Option<i64>,
    pub to_edge: Option<String>,
    pub to_lane: Option<i64>,
    pub turn: Option<String>,
    pub source: Option<String>,
    pub vehicles: Option<String>,
    pub condition: Option<String>,
    pub lines: Vec<LineString<f64>>,
}

/// The lanes into an intersection (`work.approach`), as they are.
#[derive(Clone)]
pub struct ApproachIn {
    pub unit: String,
    pub level: i32,
    pub from_edge: Option<String>,
    pub lane: Option<i64>,
    pub moves: Option<i64>,
    pub ways: Option<String>,
    pub arrow: Option<bool>,
    pub no_arrow_because: Option<String>,
}

#[derive(Clone)]
pub struct Input {
    pub units: Vec<Unit>,
    pub subsections: Vec<Subsection>,
    pub parts: Vec<Part>,
    pub marks: Vec<Mark>,
    pub ground: Vec<GroundIn>,
    pub blocks: Vec<BlockIn>,
    pub block_sides: Vec<BlockSideIn>,
    pub corridors: Vec<CorridorIn>,
    pub surfaces: Vec<SurfaceIn>,
    /// The width of a way where OSM gives one (`w<id>`).
    pub owidth: BTreeMap<String, f64>,
    pub junctions: Vec<JunctionIn>,
    /// The place of each junction node (a road's end).
    pub node_pt: BTreeMap<i64, Coord<f64>>,
    /// The named street of a way (`w<id>`), and of a name and level.
    pub way_street: BTreeMap<String, String>,
    pub name_street: BTreeMap<(String, i32), String>,
    /// The lines of the roundabouts and circular roads.
    pub roundabouts: Vec<LineString<f64>>,
    pub path_spaces: Vec<PathSpaceIn>,
    pub turns: Vec<TurnIn>,
    pub approaches: Vec<ApproachIn>,
    /// Gaps narrower than this between the street rows of the ground are closed in the street pieces of rank 1 (0 for input whose rows
    /// share their edges exactly; the chain's spaces are cut by separate overlays and leave slits of a few millimetres).
    pub close_gaps_m: f64,
}

#[derive(Clone)]
pub struct JunctionIn {
    pub intersection: String,
    pub node: i64,
    pub level: i32,
    pub cluster: Option<String>,
}

/// A path section or path intersection as `work.path_space` holds it.
#[derive(Clone)]
pub struct PathSpaceIn {
    pub id: String,
    pub kind: String,
    pub ground: String,
    pub level: i32,
    pub name: Option<String>,
    pub class: Option<String>,
    pub ways: Vec<String>,
    pub nodes: Vec<i64>,
    pub width: Option<f64>,
    pub width_source: Option<String>,
    pub width_method: Option<String>,
    pub length: Option<f64>,
    pub pred: Vec<String>,
    pub succ: Vec<String>,
    pub axis: Option<LineString<f64>>,
    pub geom: Mp,
}

/// A section as slice 1 chains it: its subsections in order, the axis through them, and what the subsections say of it.
pub struct SectionInfo {
    pub id: String,
    pub level: i32,
    pub axis: Option<LineString<f64>>,
    pub ids: Vec<String>,
    pub classes: Vec<String>,
    pub oneways: Vec<bool>,
}

pub struct Space {
    pub id: String,
    pub kind: String,
    pub parent: String,
    /// The spaces before and after, inside a section (the links through intersections come with the cut intersections).
    pub pred: Vec<String>,
    pub succ: Vec<String>,
    pub level: i32,
    pub axis: Option<LineString<f64>>,
    pub s_from: Option<f64>,
    pub s_to: Option<f64>,
    pub width: Option<f64>,
    pub oneway: Option<bool>,
    pub length: Option<f64>,
    pub left_extra: Option<f64>,
    pub name: Option<String>,
    pub geom: Mp,
}

pub struct PartRow {
    pub id: String,
    pub level: i32,
    pub road: Option<String>,
    pub side: String,
    pub space: String,
    pub typ: String,
    pub direction: Option<String>,
    pub lane: Option<i64>,
    /// (s_from, s_to, t_from, t_to), rounded to a millimetre.
    pub st: [Option<f64>; 4],
    pub axis: Option<LineString<f64>>,
    pub pred: Vec<String>,
    pub succ: Vec<String>,
    pub width_m: Option<f64>,
    pub width_source: Option<String>,
    pub length_m: Option<f64>,
    pub extra: PartExtra,
    pub r#ref: Option<String>,
    pub geom: Mp,
}

pub struct MarkRow {
    pub id: String,
    pub level: i32,
    pub source: Option<String>,
    pub method: Option<String>,
    pub reference: Option<String>,
    pub space: String,
    pub kind: String,
    pub parent: Option<String>,
    pub parent_rank: i32,
    pub st: [Option<f64>; 4],
    pub lines: Vec<LineString<f64>>,
}

/// A junction node and the space that holds it.
pub struct JunctionRow {
    pub intersection: String,
    pub node: i64,
    pub level: i32,
    pub cluster: Option<String>,
    pub space: Option<String>,
}

/// The driving or the walking side of a space: its parts joined, and the kerb.
pub struct SideRow {
    pub id: String,
    pub kind: String,
    pub parent: String,
    pub level: i32,
    pub kerb: Option<Vec<LineString<f64>>>,
    pub kerb_source: Option<String>,
    pub kerb_method: Option<String>,
    pub geom: Mp,
}

pub struct TurnRow {
    pub space: String,
    pub vehicles: Option<String>,
    pub source: Option<String>,
    pub lines: Vec<LineString<f64>>,
    pub level: i32,
    pub from_edge: Option<String>,
    pub from_lane: Option<i64>,
    pub to_edge: Option<String>,
    pub to_lane: Option<i64>,
    pub turn: Option<String>,
}

pub struct Output {
    /// The levels the model holds (one area row each).
    pub levels: Vec<i32>,
    pub spaces: Vec<Space>,
    pub parts: Vec<PartRow>,
    pub marks: Vec<MarkRow>,
    pub ground: Vec<GroundRow>,
    pub plot_pieces: Vec<PlotPieceRow>,
    pub stretches: Vec<StretchRow>,
    pub arms: Vec<ArmRow>,
    pub streets: Vec<StreetRow>,
    pub junctions: Vec<JunctionRow>,
    pub sides: Vec<SideRow>,
    pub turns: Vec<TurnRow>,
    pub approaches: Vec<ApproachIn>,
}

/// (s_from, s_to, t_from, t_to) of the points on `axis`: s along it, t across it, left positive (`product._st`).
pub fn st(axis: &LineString<f64>, pts: &[Coord<f64>]) -> Option<[f64; 4]> {
    let len = lines::length(axis);
    if pts.is_empty() || len == 0.0 {
        return None;
    }
    let mut r = [f64::INFINITY, f64::NEG_INFINITY, f64::INFINITY, f64::NEG_INFINITY];
    for p in pts {
        let s = lines::project(axis, *p);
        let (a, b, c) = (lines::interpolate(axis, (s - 0.5).max(0.0))?, lines::interpolate(axis, (s + 0.5).min(len))?, lines::interpolate(axis, s)?);
        let side = (b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x);
        let t = if side >= 0.0 { 1.0 } else { -1.0 } * (p.x - c.x).hypot(p.y - c.y);
        r = [r[0].min(s), r[1].max(s), r[2].min(t), r[3].max(t)];
    }
    Some(r)
}

/// Lines end to end, each turned to continue the one before: one line, each line's (s_from, s_to) on it, and the lines as turned.
pub fn chain(lines_in: &[&LineString<f64>]) -> (Option<LineString<f64>>, Vec<(f64, f64)>, Vec<LineString<f64>>) {
    let d = |a: Coord<f64>, b: Coord<f64>| (a.x - b.x).hypot(a.y - b.y);
    let (mut coords, mut ranges, mut turned): (Vec<Coord<f64>>, Vec<(f64, f64)>, Vec<LineString<f64>>) = (vec![], vec![], vec![]);
    for ln in lines_in {
        let mut c = ln.0.clone();
        if let Some(&last) = coords.last() {
            if d(*c.last().unwrap(), last) < d(c[0], last) {
                c.reverse();
            }
        }
        turned.push(LineString::new(c.clone()));
        let s0 = if coords.len() > 1 { lines::length(&LineString::new(coords.clone())) } else { 0.0 };
        match coords.last() {
            Some(&last) if d(c[0], last) < 0.01 => coords.extend(c[1..].iter().copied()),
            _ => coords.extend(c.iter().copied()),
        }
        ranges.push((s0, s0 + lines::length(ln)));
    }
    ((coords.len() > 1).then(|| LineString::new(coords)), ranges, turned)
}

/// The length of the outline of the polygons (shapely's `length` of a polygon).
fn perimeter(m: &Mp) -> f64 {
    m.0.iter().flat_map(|p| std::iter::once(p.exterior()).chain(p.interiors())).map(lines::length).sum()
}

fn round3(v: f64) -> f64 {
    (v * 1000.0).round() / 1000.0
}

fn points_of(m: &Mp) -> Vec<Coord<f64>> {
    m.0.iter().flat_map(|p| p.exterior().0.iter().copied()).collect()
}

fn k_of(id: &str) -> i64 {
    id.rsplit_once('/').and_then(|(_, k)| k.parse().ok()).unwrap_or(0)
}

pub(crate) fn rings(m: &Mp) -> Vec<&LineString<f64>> {
    m.0.iter().flat_map(|p| std::iter::once(p.exterior()).chain(p.interiors())).collect()
}

impl Input {
    /// The input with every polygon wound the way `i_overlay` reads it: a polygon wound the other way is lost in a union.
    pub fn oriented(&self) -> Input {
        let mut o = self.clone();
        o.units.iter_mut().for_each(|u| u.geom = ops::orient(&u.geom));
        o.parts.iter_mut().for_each(|p| p.geom = ops::orient(&p.geom));
        o.ground.iter_mut().for_each(|g| g.geom = ops::orient(&g.geom));
        o.blocks.iter_mut().for_each(|b| b.geom = ops::orient(&b.geom));
        o.path_spaces.iter_mut().for_each(|x| x.geom = ops::orient(&x.geom));
        o
    }
}

pub fn build(inp: &Input) -> Output {
    let inp = &inp.oriented();
    // ---- the sections: the subsections chained, a space row for each subsection
    let in_units: HashSet<&str> = inp.units.iter().map(|u| u.id.as_str()).collect();
    let mut by_section: BTreeMap<&str, Vec<&Subsection>> = BTreeMap::new();
    for s in &inp.subsections {
        by_section.entry(s.section.as_str()).or_default().push(s);
    }
    let mut spaces: Vec<Space> = Vec::new();
    let mut axis_of: BTreeMap<String, (LineString<f64>, f64)> = BTreeMap::new();
    let mut section_infos: Vec<SectionInfo> = Vec::new();
    for (sec, mut ids) in by_section {
        ids.sort_by_key(|s| k_of(&s.id));
        let mut ordered: Vec<&Subsection> = ids.iter().copied().filter(|s| s.line.is_some()).collect();
        ordered.extend(ids.iter().copied().filter(|s| s.line.is_none()));
        let lines_in: Vec<&LineString<f64>> = ordered.iter().filter_map(|s| s.line.as_ref()).collect();
        let (chained, ranges, turned) = chain(&lines_in);
        section_infos.push(SectionInfo {
            id: sec.to_string(),
            level: ordered[0].level,
            axis: chained,
            ids: ordered.iter().map(|s| s.id.clone()).collect(),
            classes: ordered.iter().filter_map(|s| s.class.clone()).filter(|c| !c.is_empty()).collect(),
            oneways: ordered.iter().map(|s| s.oneway.unwrap_or(false)).collect(),
        });
        for (j, s) in ordered.iter().enumerate() {
            if !in_units.contains(s.id.as_str()) {
                continue;
            }
            let axis = turned.get(j).cloned();
            let range = ranges.get(j).copied();
            if let (Some(a), Some(r)) = (&axis, range) {
                axis_of.insert(s.id.clone(), (a.clone(), r.0));
            }
            let j = ordered.iter().position(|o| o.id == s.id).unwrap();
            spaces.push(Space {
                id: s.id.clone(),
                kind: "subsection".into(),
                parent: sec.to_string(),
                pred: if j > 0 { vec![ordered[j - 1].id.clone()] } else { vec![] },
                succ: ordered.get(j + 1).map(|o| vec![o.id.clone()]).unwrap_or_default(),
                level: s.level,
                axis,
                s_from: range.map(|r| r.0),
                s_to: range.map(|r| r.1),
                width: s.width,
                oneway: s.oneway,
                length: s.length,
                left_extra: s.left_extra,
                name: None,
                geom: inp.units.iter().find(|u| u.id == s.id).map(|u| u.geom.clone()).unwrap(),
            });
        }
    }

    // ---- rank 1 and the stretches (the parts below use the sections' ends)
    let mut levels: Vec<i32> = inp.units.iter().map(|u| u.level).chain(inp.ground.iter().map(|g| g.level)).chain(std::iter::once(0)).collect();
    levels.sort();
    levels.dedup();
    let (ground, plot_pieces, street_best) = rank1::build(inp, &levels);
    let (stretches, arms, streets, section_ends) = stretch::build(inp, &section_infos, &street_best);

    // ---- an intersection cut into one piece per junction node (a roundabout: its ring sectors and its centre)
    let unit_level: BTreeMap<&str, i32> = inp.units.iter().map(|u| (u.id.as_str(), u.level)).collect();
    let mut jnodes: BTreeMap<&str, Vec<i64>> = BTreeMap::new();
    for j in &inp.junctions {
        jnodes.entry(j.intersection.as_str()).or_default().push(j.node);
    }
    struct SubInt {
        id: String,
        parent: String,
        kind: String,
        level: i32,
        geom: Mp,
    }
    let mut subint: Vec<SubInt> = Vec::new();
    let mut sub_of: BTreeMap<String, Vec<usize>> = BTreeMap::new();
    for u in inp.units.iter().filter(|u| u.kind == "intersection") {
        let idx = urbanstyle_geo::index::SegIndex::new(&u.geom);
        let rings: Vec<LineString<f64>> = inp.roundabouts.iter().filter(|ln| idx.clip_line(ln, true).iter().map(lines::length).sum::<f64>() > stretch::RING_M).cloned().collect();
        let nodes: Vec<(i64, Coord<f64>)> = jnodes.get(u.id.as_str()).map(|v| v.iter().filter_map(|n| inp.node_pt.get(n).map(|p| (*n, *p))).collect()).unwrap_or_default();
        let islands: Vec<&Mp> = inp.parts.iter().filter(|p| p.unit == u.id && p.typ == "island").map(|p| &p.geom).collect();
        for (key, geom) in intersect::cut(&u.geom, &nodes, &rings, &islands) {
            let tail = key.clone().unwrap_or_else(|| u.id.split_once('-').map_or(u.id.clone(), |x| x.1.to_string()));
            let kind = if key.as_deref() == Some("centre") { "centre" } else if !rings.is_empty() { "ring sector" } else { "sub-intersection" };
            sub_of.entry(u.id.clone()).or_default().push(subint.len());
            subint.push(SubInt { id: format!("{}/{}", u.id, tail), parent: u.id.clone(), kind: kind.into(), level: u.level, geom });
        }
    }
    let near_sub = |i: &str, pt: Coord<f64>| -> String {
        match sub_of.get(i) {
            Some(v) if !v.is_empty() => {
                let d = |k: usize| Euclidean.distance(&subint[k].geom, &geo::Point::from(pt));
                subint[*v.iter().min_by(|&&a, &&b| d(a).partial_cmp(&d(b)).unwrap()).unwrap()].id.clone()
            }
            _ => i.to_string(),
        }
    };

    // ---- the parts of an intersection cut along the same lines (a part never crosses a cut); one junction area for each piece
    struct WPart<'a> {
        src: &'a Part,
        unit: String,
        geom: Mp,
        orig: String,
        id: String,
    }
    let mut split: Vec<WPart> = Vec::new();
    for p in &inp.parts {
        match sub_of.get(&p.unit) {
            None => split.push(WPart { src: p, unit: p.unit.clone(), geom: p.geom.clone(), orig: p.id.clone(), id: p.id.clone() }),
            Some(ks) => {
                for &k in ks {
                    let piece = ops::intersection(&p.geom, &subint[k].geom);
                    let polys: Vec<Mp> = piece.0.into_iter().filter(|q| geo::Area::unsigned_area(q) > 0.01).map(|q| Mp::new(vec![q])).collect();
                    if !polys.is_empty() {
                        split.push(WPart { src: p, unit: subint[k].id.clone(), geom: ops::union_all(polys.iter()), orig: p.id.clone(), id: p.id.clone() });
                    }
                }
            }
        }
    }
    let is_sub: HashSet<&str> = subint.iter().map(|x| x.id.as_str()).collect();
    {
        let mut first: BTreeMap<String, usize> = BTreeMap::new();
        for (i, p) in split.iter().enumerate() {
            if is_sub.contains(p.unit.as_str()) && p.src.typ == "junction area" {
                first.entry(p.unit.clone()).or_insert(i);
            }
        }
        for (unit, &f) in &first {
            let all: Vec<Mp> = split.iter().filter(|p| &p.unit == unit && p.src.typ == "junction area").map(|p| p.geom.clone()).collect();
            split[f].geom = ops::union_all(all.iter());
        }
        let keep: HashSet<usize> = first.values().copied().collect();
        let mut i = 0;
        split.retain(|p| {
            let ok = !(is_sub.contains(p.unit.as_str()) && p.src.typ == "junction area" && !keep.contains(&i));
            i += 1;
            ok
        });
    }
    // a part under MIN_PART_M2 joins the part of its side it shares the longest edge with
    let side_of = |p: &WPart| (p.unit.clone(), WALKING.contains(&p.src.typ.as_str()));
    let mut by_side: BTreeMap<(String, bool), Vec<usize>> = BTreeMap::new();
    for (i, p) in split.iter().enumerate() {
        by_side.entry(side_of(p)).or_default().push(i);
    }
    let mut order: Vec<usize> = (0..split.len()).collect();
    order.sort_by(|&a, &b| ops::area(&split[a].geom).partial_cmp(&ops::area(&split[b].geom)).unwrap());
    let mut gone: HashSet<usize> = HashSet::new();
    for i in order {
        if ops::area(&split[i].geom) >= MIN_PART_M2 {
            break;
        }
        let near = NearIndex::new(rings(&split[i].geom));
        let nb: Vec<usize> = by_side[&side_of(&split[i])].iter().copied().filter(|&x| x != i && !gone.contains(&x)).collect();
        let best = nb.iter().map(|&x| (x, near.length_within(rings(&split[x].geom), NEAR_M))).fold(None::<(usize, f64)>, |b, c| match b {
            Some(bb) if bb.1 >= c.1 => Some(bb),
            _ => Some(c),
        });
        let Some((x, l)) = best else { continue };
        if l <= 0.0 {
            continue;
        }
        let u = ops::union(&split[x].geom, &split[i].geom);
        split[x].geom = u;
        gone.insert(i);
    }
    let mut parts: Vec<WPart> = split.into_iter().enumerate().filter(|(i, _)| !gone.contains(i)).map(|(_, p)| p).collect();
    // the pieces' parts are numbered in each piece
    {
        let mut idx: Vec<usize> = (0..parts.len()).filter(|&i| is_sub.contains(parts[i].unit.as_str())).collect();
        idx.sort_by(|&a, &b| (&parts[a].unit, &parts[a].orig).cmp(&(&parts[b].unit, &parts[b].orig)));
        let mut n: BTreeMap<String, usize> = BTreeMap::new();
        for i in idx {
            let c = n.entry(parts[i].unit.clone()).or_insert(0);
            *c += 1;
            parts[i].id = format!("{}#{}", parts[i].unit, c);
        }
    }

    // ---- the part rows: the place on the space's axis (a piece of an intersection has no axis), and the part's own axis
    let mut part_rows: Vec<PartRow> = Vec::new();
    for p in &parts {
        let side = format!("{}:{}", p.unit, if WALKING.contains(&p.src.typ.as_str()) { "w" } else { "d" });
        let level = unit_level.get(p.unit.as_str()).copied().or_else(|| subint.iter().find(|x| x.id == p.unit).map(|x| x.level)).unwrap_or(0);
        let mut row = PartRow {
            id: p.id.clone(),
            level,
            road: p.src.road.clone(),
            side,
            space: p.unit.clone(),
            typ: p.src.typ.clone(),
            direction: p.src.direction.clone(),
            lane: p.src.lane,
            st: [None; 4],
            axis: None,
            pred: vec![],
            succ: vec![],
            width_m: p.src.extra.width_m,
            width_source: p.src.extra.width_source.clone(),
            length_m: Some((perimeter(&p.geom) / 2.0 * 10.0).round() / 10.0),
            extra: p.src.extra.clone(),
            r#ref: p.src.r#ref.clone(),
            geom: p.geom.clone(),
        };
        if let Some((ax, off)) = axis_of.get(&p.unit) {
            let raw = st(ax, &points_of(&p.geom));
            if let Some(r) = raw {
                row.st = [Some(round3(r[0] + off)), Some(round3(r[1] + off)), Some(round3(r[2])), Some(round3(r[3]))];
                if !NO_AXIS.contains(&p.src.typ.as_str()) && r[1] - r[0] > 0.5 {
                    let piece = lines::substring(ax, r[0], r[1]);
                    if lines::length(&piece) > 0.0 {
                        let mut a = lines::shift(&piece, (r[2] + r[3]) / 2.0);
                        if p.src.direction.as_deref() == Some("backward") {
                            a.0.reverse();
                        }
                        row.axis = Some(a);
                    }
                }
            }
        }
        part_rows.push(row);
    }

    // ---- the links of the spaces: a subsection goes on into the next of its section, the first and the last into the piece of the
    // intersection its axis reaches; a piece of an intersection takes its arms (and its neighbours)
    let ends_sub: BTreeMap<&str, [Option<String>; 2]> = section_ends
        .iter()
        .map(|e| {
            let sd = section_infos.iter().find(|s| s.id == e.section).unwrap();
            let sub = |k: usize| e.ends[k].as_ref().map(|i| match &sd.axis {
                Some(ax) => near_sub(i, if k == 0 { ax.0[0] } else { *ax.0.last().unwrap() }),
                None => i.clone(),
            });
            (e.section.as_str(), [sub(0), sub(1)])
        })
        .collect();
    let mut preds: BTreeMap<String, Vec<String>> = BTreeMap::new();
    let mut succs: BTreeMap<String, Vec<String>> = BTreeMap::new();
    let mut oneway_of: BTreeMap<&str, bool> = BTreeMap::new();
    for sd in &section_infos {
        let es = &ends_sub[sd.id.as_str()];
        for (j, s) in sd.ids.iter().enumerate() {
            oneway_of.insert(s.as_str(), sd.oneways[j]);
            preds.insert(s.clone(), if j > 0 { vec![sd.ids[j - 1].clone()] } else { es[0].iter().cloned().collect() });
            succs.insert(s.clone(), if j + 1 < sd.ids.len() { vec![sd.ids[j + 1].clone()] } else { es[1].iter().cloned().collect() });
        }
    }
    let (sp, ss) = (preds.clone(), succs.clone());
    let touch = |a: &Mp, b: &Mp| NearIndex::new(rings(a)).length_within(rings(b), NEAR_M);
    for sub in &subint {
        let nb: Vec<String> = sub_of[&sub.parent].iter().map(|&k| &subint[k]).filter(|o| o.id != sub.id && touch(&sub.geom, &o.geom) >= TOUCH_M).map(|o| o.id.clone()).collect();
        // a section that ends at the piece arrives there (the piece's predecessor) and, unless it is one-way, leaves from it too
        let mut p2: BTreeSet<String> = nb.iter().cloned().collect();
        let mut q2: BTreeSet<String> = nb.iter().cloned().collect();
        for (s, v) in &ss {
            if v.contains(&sub.id) {
                p2.insert(s.clone());
            }
        }
        for (s, v) in &sp {
            if v.contains(&sub.id) {
                q2.insert(s.clone());
                if !oneway_of.get(s.as_str()).copied().unwrap_or(false) {
                    p2.insert(s.clone());
                }
            }
        }
        for (s, v) in &ss {
            if v.contains(&sub.id) && !oneway_of.get(s.as_str()).copied().unwrap_or(false) {
                q2.insert(s.clone());
            }
        }
        preds.insert(sub.id.clone(), p2.into_iter().collect());
        succs.insert(sub.id.clone(), q2.into_iter().collect());
    }
    for sp_ in spaces.iter_mut() {
        if let (Some(p), Some(q)) = (preds.get(&sp_.id), succs.get(&sp_.id)) {
            sp_.pred = p.clone();
            sp_.succ = q.clone();
        }
    }
    let iname = |i: &str| -> Option<String> {
        let mut roads: Vec<String> = inp.parts.iter().filter(|p| p.unit == i && p.typ == "lane").filter_map(|p| p.road.clone()).filter(|r| !r.is_empty()).collect();
        roads.sort();
        roads.dedup();
        (!roads.is_empty()).then(|| roads.join(" / "))
    };
    for sub in &subint {
        spaces.push(Space {
            id: sub.id.clone(),
            kind: sub.kind.clone(),
            parent: sub.parent.clone(),
            pred: preds[&sub.id].clone(),
            succ: succs[&sub.id].clone(),
            level: sub.level,
            axis: None,
            s_from: None,
            s_to: None,
            width: None,
            oneway: None,
            length: None,
            left_extra: None,
            name: iname(&sub.parent),
            geom: sub.geom.clone(),
        });
    }

    // ---- the lane links: inside a section, at a section's end, through an intersection by SUMO's moves
    {
        let mut by_unit: BTreeMap<String, Vec<usize>> = BTreeMap::new();
        for (i, p) in part_rows.iter().enumerate() {
            if p.typ == "lane" {
                by_unit.entry(p.space.clone()).or_default().push(i);
            }
        }
        let mut links: Vec<(usize, usize)> = Vec::new();
        for sd in &section_infos {
            for w in sd.ids.windows(2) {
                let (Some(xs), Some(ys)) = (by_unit.get(&w[0]), by_unit.get(&w[1])) else { continue };
                for &a in xs {
                    let near = NearIndex::new(rings(&part_rows[a].geom));
                    for &b in ys {
                        let (pa, pb) = (&part_rows[a], &part_rows[b]);
                        if pa.direction == pb.direction && pa.lane == pb.lane && near.length_within(rings(&pb.geom), NEAR_M) >= TOUCH_M {
                            links.push(if pa.direction.as_deref() != Some("backward") { (a, b) } else { (b, a) });
                        }
                    }
                }
            }
            let es = &ends_sub[sd.id.as_str()];
            for e in 0..2 {
                let Some(i_) = &es[e] else { continue };
                let s_end = if e == 0 { &sd.ids[0] } else { sd.ids.last().unwrap() };
                let (Some(xs), Some(ys)) = (by_unit.get(s_end), by_unit.get(i_)) else { continue };
                for &a in xs {
                    let near = NearIndex::new(rings(&part_rows[a].geom));
                    for &b in ys {
                        let (pa, pb) = (&part_rows[a], &part_rows[b]);
                        if pa.road == pb.road && near.length_within(rings(&pb.geom), NEAR_M) >= TOUCH_M {
                            // the lane runs into the intersection
                            let into = (e == 1) == (pa.direction.as_deref() != Some("backward"));
                            links.push(if into { (a, b) } else { (b, a) });
                        }
                    }
                }
            }
        }
        // a turn starts in the lane that arrives (in the subsection before the stop line, or in the intersection) and ends in the lane that
        // leaves: the lanes of the intersection and of the subsections at its arms
        for t in &inp.turns {
            let mine: Vec<String> = sub_of.get(&t.unit).map(|v| v.iter().map(|&k| subint[k].id.clone()).collect()).unwrap_or_else(|| vec![t.unit.clone()]);
            let mut cands: Vec<usize> = mine.iter().flat_map(|s| by_unit.get(s).cloned().unwrap_or_default()).collect();
            let mut nbs: BTreeSet<&String> = BTreeSet::new();
            for s in &mine {
                nbs.extend(preds.get(s).into_iter().flatten());
                nbs.extend(succs.get(s).into_iter().flatten());
            }
            for s in nbs.into_iter().filter(|s| !mine.contains(s)) {
                cands.extend(by_unit.get(s).cloned().unwrap_or_default());
            }
            let Some(ln) = t.lines.first() else { continue };
            if cands.is_empty() || ln.0.is_empty() {
                continue;
            }
            let (a_pt, b_pt) = (geo::Point::from(ln.0[0]), geo::Point::from(*ln.0.last().unwrap()));
            let near = |pt: &geo::Point<f64>| *cands.iter().min_by(|&&x, &&y| Euclidean.distance(&part_rows[x].geom, pt).partial_cmp(&Euclidean.distance(&part_rows[y].geom, pt)).unwrap()).unwrap();
            let (a, b) = (near(&a_pt), near(&b_pt));
            if a != b && Euclidean.distance(&part_rows[a].geom, &a_pt) < TURN_M && Euclidean.distance(&part_rows[b].geom, &b_pt) < TURN_M {
                links.push((a, b));
            }
        }
        for (a, b) in links {
            let (ia, ib) = (part_rows[a].id.clone(), part_rows[b].id.clone());
            part_rows[a].succ.push(ib);
            part_rows[b].pred.push(ia);
        }
        for p in &mut part_rows {
            p.pred.sort();
            p.pred.dedup();
            p.succ.sort();
            p.succ.dedup();
        }
    }

    // ---- the path spaces: a space and one part each
    for x in &inp.path_spaces {
        spaces.push(Space {
            id: x.id.clone(),
            kind: x.kind.clone(),
            parent: x.id.clone(),
            pred: x.pred.clone(),
            succ: x.succ.clone(),
            level: x.level,
            axis: x.axis.clone(),
            s_from: x.axis.as_ref().map(|_| 0.0),
            s_to: x.length,
            width: x.width,
            oneway: if x.kind == "path section" { Some(false) } else { None },
            length: x.length,
            left_extra: None,
            name: x.name.clone(),
            geom: x.geom.clone(),
        });
        let raw = x.axis.as_ref().and_then(|ax| st(ax, &points_of(&x.geom)));
        part_rows.push(PartRow {
            id: format!("{}#1", x.id),
            level: x.level,
            road: None,
            side: format!("{}:w", x.id),
            space: x.id.clone(),
            typ: if x.class.as_deref() == Some("steps") { "steps" } else { "path" }.into(),
            direction: None,
            lane: None,
            st: match raw {
                Some(r) => [Some(round3(r[0])), Some(round3(r[1])), Some(round3(r[2])), Some(round3(r[3]))],
                None => [None; 4],
            },
            axis: x.axis.clone(),
            pred: vec![],
            succ: vec![],
            width_m: x.width,
            width_source: x.width_source.clone(),
            length_m: x.length,
            extra: PartExtra { width_method: x.width_method.clone(), source: Some("urbanstyle".into()), method: Some("derived".into()), ..Default::default() },
            r#ref: Some(x.ways.join(",")),
            geom: x.geom.clone(),
        });
    }

    // ---- the marks: an intersection's mark lies in the piece that holds its middle; numbered by space and kind, in the order of their middles
    let mid = |m: &Mark| -> Option<Coord<f64>> {
        // (the point of the line nearest to its centre among its inner vertices, as GEOS picks it)
        let c = geo::MultiLineString::new(m.lines.clone()).centroid()?;
        let all: Vec<Coord<f64>> = m.lines.iter().flat_map(|l| l.0.iter().copied()).collect();
        let inner: Vec<Coord<f64>> = m.lines.iter().flat_map(|l| l.0.iter().skip(1).take(l.0.len().saturating_sub(2)).copied()).collect();
        let pool = if inner.is_empty() { all } else { inner };
        pool.into_iter().min_by(|a, b| (a.x - c.x()).hypot(a.y - c.y()).partial_cmp(&(b.x - c.x()).hypot(b.y - c.y())).unwrap())
    };
    let mut marks: Vec<(String, &Mark, (f64, f64))> = inp
        .marks
        .iter()
        .map(|m| {
            let unit = if sub_of.contains_key(&m.unit) { mid(m).map_or(m.unit.clone(), |pt| near_sub(&m.unit, pt)) } else { m.unit.clone() };
            let c = geo::MultiLineString::new(m.lines.clone()).centroid().map_or((0.0, 0.0), |c| (c.x(), c.y()));
            (unit, m, c)
        })
        .collect();
    marks.sort_by(|a, b| (&a.0, &a.1.typ).cmp(&(&b.0, &b.1.typ)).then(a.2 .0.partial_cmp(&b.2 .0).unwrap()).then(a.2 .1.partial_cmp(&b.2 .1).unwrap()));
    let mut parts_by_unit: BTreeMap<&str, Vec<&PartRow>> = BTreeMap::new();
    for p in &part_rows {
        parts_by_unit.entry(p.space.as_str()).or_default().push(p);
    }
    let mut seq: BTreeMap<(String, String), usize> = BTreeMap::new();
    let mut mark_rows = Vec::new();
    for (unit, m, _) in &marks {
        let n = seq.entry((unit.clone(), m.typ.clone())).or_insert(0);
        *n += 1;
        let pts: Vec<Coord<f64>> = m.lines.iter().flat_map(|l| l.0.iter().copied()).collect();
        let place = axis_of.get(unit).and_then(|(ax, off)| st(ax, &pts).map(|r| [Some(round3(r[0] + off)), Some(round3(r[1] + off)), Some(round3(r[2])), Some(round3(r[3]))])).unwrap_or([None; 4]);
        let (parent, prank) = if m.typ == "kerb" {
            (Some(format!("{unit}:d")), 4)
        } else {
            // the part that holds the middle of the mark, else the nearest that meets it
            let pt = mid(m);
            let cands = parts_by_unit.get(unit.as_str()).cloned().unwrap_or_default();
            let inside = pt.and_then(|pt| cands.iter().filter(|p| geo::Contains::contains(&p.geom, &geo::Point::from(pt))).min_by(|a, b| ops::area(&a.geom).partial_cmp(&ops::area(&b.geom)).unwrap()));
            let found = inside.copied().or_else(|| {
                let pt = geo::Point::from(pt?);
                cands.iter().copied().filter(|p| m.lines.iter().any(|l| Euclidean.distance(&p.geom, l) < 1e-9)).min_by(|a, b| Euclidean.distance(&a.geom, &pt).partial_cmp(&Euclidean.distance(&b.geom, &pt)).unwrap())
            });
            (found.map(|p| p.id.clone()), 5)
        };
        mark_rows.push(MarkRow { id: format!("{}:{}:{}", unit, m.typ, n), level: m.level, source: m.source.clone(), method: m.method.clone(), reference: m.reference.clone(), space: unit.clone(), kind: m.typ.clone(), parent, parent_rank: prank, st: place, lines: m.lines.clone() });
    }

    // ---- the sides: the parts of one side joined, and the kerb of the driving side
    let mut kerbs: BTreeMap<&str, Vec<&Mark>> = BTreeMap::new();
    for (unit, m, _) in &marks {
        if m.typ == "kerb" {
            kerbs.entry(unit.as_str()).or_default().push(m);
        }
    }
    let mut by_side_rows: BTreeMap<&str, (&str, i32, Vec<&Mp>)> = BTreeMap::new();
    for p in &part_rows {
        by_side_rows.entry(p.side.as_str()).or_insert((p.space.as_str(), p.level, vec![])).2.push(&p.geom);
    }
    let sides: Vec<SideRow> = by_side_rows
        .into_iter()
        .map(|(sid, (unit, level, gs))| {
            let k = if sid.ends_with(":d") { kerbs.get(unit).cloned().unwrap_or_default() } else { vec![] };
            SideRow {
                id: sid.to_string(),
                kind: if sid.ends_with(":w") { "walking" } else { "driving" }.into(),
                parent: unit.to_string(),
                level,
                kerb: (!k.is_empty()).then(|| k.iter().flat_map(|m| m.lines.clone()).collect()),
                kerb_source: stretch::common(&k.iter().filter_map(|m| m.source.clone()).collect::<Vec<_>>()),
                kerb_method: stretch::common(&k.iter().filter_map(|m| m.method.clone()).collect::<Vec<_>>()),
                geom: ops::union_all(gs.into_iter()),
            }
        })
        .collect();

    // ---- the junction nodes, the turns and the approaches
    let junctions: Vec<JunctionRow> = inp
        .junctions
        .iter()
        .map(|j| {
            let own = format!("{}/{}", j.intersection, j.node);
            let space = if is_sub.contains(own.as_str()) { Some(own) } else { inp.node_pt.get(&j.node).map(|pt| near_sub(&j.intersection, *pt)) };
            JunctionRow { intersection: j.intersection.clone(), node: j.node, level: j.level, cluster: j.cluster.clone(), space }
        })
        .collect();
    let turns: Vec<TurnRow> = inp
        .turns
        .iter()
        .map(|t| TurnRow {
            vehicles: t.vehicles.clone(),
            source: t.source.clone(),
            lines: t.lines.clone(),
            space: t.lines.first().and_then(|l| l.0.first()).map_or(t.unit.clone(), |pt| near_sub(&t.unit, *pt)),
            level: t.level,
            from_edge: t.from_edge.clone(),
            from_lane: t.from_lane,
            to_edge: t.to_edge.clone(),
            to_lane: t.to_lane,
            turn: t.turn.clone(),
        })
        .collect();
    Output { levels, spaces, parts: part_rows, marks: mark_rows, ground, plot_pieces, stretches, arms, streets, junctions, sides, turns, approaches: inp.approaches.clone() }
}

/// The numbers this crate chooses, for the manifest `urban.meta` (`chosen.<name>`): name, value, what it is.
pub fn chosen() -> Vec<(String, f64, String)> {
    vec![
        ("model.MIN_PART_M2".to_string(), MIN_PART_M2, "A part under this joins the part of its side it shares the longest edge with.".to_string()),
        ("model.TOUCH_M".to_string(), TOUCH_M, "Two lanes share a joint or a stop line when their outlines touch along at least this length.".to_string()),
        ("model.TURN_M".to_string(), TURN_M, "A turn's guide line starts in the lane nearest its first point, and ends in the lane nearest its last, within this.".to_string()),
    ]
}
