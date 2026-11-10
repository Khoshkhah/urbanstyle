//! The conformance checks of a built model (docs/design/street-space-spec.md, section 8), as `checks.py` runs them on the tables of a build:
//! one row for each invariant, with its count. Group 1, here: the partitions. Rank 3 partitions the street (U1 to U9), rank 1 partitions
//! the area (G1 to G3), the surfaces cover their ground item (L1, L2), no space reaches into a block (B7), and a few reports (B1, B8,
//! U11 to U13). The geometry is the one the build stored (metres): a polygon in several parts or not valid is a fault (U2).
use geo::{BoundingRect, Coord, Distance, Euclidean, LineString};
use std::collections::{BTreeMap, BTreeSet, HashMap};
use urbanstyle_geo::index::{Index, SegIndex};
use urbanstyle_geo::lines;
use urbanstyle_geo::ops::{self, Mp};

pub mod roadway;
pub mod rules;

/// A hairline of the storage in lon/lat: a polygon is read 1 cm inside its outline for the overlaps.
const HAIRLINE_M: f64 = 0.01;

#[derive(Clone)]
pub struct Unit {
    pub id: String,
    pub kind: String,
    pub level: i32,
    pub geom: Mp,
}

#[derive(Clone)]
pub struct PartIn {
    pub unit: String,
    pub id: String,
    pub level: i32,
    pub typ: String,
    pub width_method: Option<String>,
    pub source: Option<String>,
    pub width: Option<f64>,
    pub geom: Mp,
}

#[derive(Clone)]
pub struct GroundIn {
    pub id: String,
    pub level: i32,
    pub typ: String,
    pub geom: Mp,
}

#[derive(Clone)]
pub struct SurfaceIn {
    pub id: String,
    pub ground: String,
    pub geom: Mp,
}

#[derive(Clone)]
pub struct BlockIn {
    pub id: String,
    pub geom: Mp,
}

#[derive(Clone)]
pub struct JunctionIn {
    pub intersection: String,
    pub level: i32,
    pub node: i64,
}

#[derive(Clone)]
pub struct SubsectionIn {
    pub id: String,
    pub level: i32,
    pub line: Option<LineString<f64>>,
    pub width: Option<f64>,
}

#[derive(Clone)]
pub struct MarkIn {
    pub unit: String,
    pub typ: String,
    pub source: Option<String>,
    pub lines: Vec<LineString<f64>>,
}

#[derive(Clone)]
pub struct ApproachIn {
    pub unit: String,
    pub from_edge: Option<String>,
    pub moves: Option<i64>,
    pub ways: Option<String>,
    pub arrow: Option<bool>,
    pub no_arrow_because: Option<String>,
}

#[derive(Clone)]
pub struct Input {
    pub area: Mp,
    pub units: Vec<Unit>,
    pub parts: Vec<PartIn>,
    pub ground: Vec<GroundIn>,
    pub surfaces: Vec<SurfaceIn>,
    pub blocks: Vec<BlockIn>,
    /// The buildings that reach level 0.
    pub buildings: Vec<Mp>,
    pub node_pt: BTreeMap<i64, Coord<f64>>,
    pub junctions: Vec<JunctionIn>,
    pub subsections: Vec<SubsectionIn>,
    pub approaches: Vec<ApproachIn>,
    /// The guide lines (SUMO's moves) by level.
    pub guides: Vec<(i32, Vec<LineString<f64>>)>,
    /// The road and walkway lines.
    pub roads: Vec<RoadIn>,
    /// The kerbs and the lane and centre lines of level 0.
    pub marks: Vec<MarkIn>,
    /// The section of each subsection.
    pub sections: BTreeMap<String, String>,
    /// Two outlines this near are one edge (W2). `roadway::SHARED_M` for spaces that share their vertices exactly; a grid for spaces
    /// that were snapped to it.
    pub shared_m: f64,
}

#[derive(Clone)]
pub struct RoadIn {
    pub osm_id: i64,
    pub src: Option<i64>,
    pub dst: Option<i64>,
    pub level: i32,
    pub typ: String,
    /// A street (`blocks.street_sql`), not a service road or a driveway.
    pub street: bool,
    pub line: Option<LineString<f64>>,
    pub class: Option<String>,
    pub width: Option<f64>,
    pub subtype: Option<String>,
}

/// One row of the report. `hard`: a count that is not zero fails the build; else it is information.
pub struct Check {
    pub id: &'static str,
    pub what: String,
    pub count: usize,
    pub hard: bool,
}

impl Check {
    pub fn status(&self) -> &'static str {
        if self.count == 0 {
            "pass"
        } else if self.hard {
            "fail"
        } else {
            "info"
        }
    }
}

pub(crate) fn check(id: &'static str, hard: bool, count: usize, what: impl Into<String>) -> Check {
    Check { id, what: what.into(), count, hard }
}

/// A polygon read 1 cm inside its outline.
fn inner(g: &Mp) -> Mp {
    ops::buffer(&ops::orient(g), -HAIRLINE_M)
}

/// The pairs `(i, j)`, `i < j`, of the items in the same group whose outlines overlap by more than `min_m2`: their number, and the area of
/// all the overlaps of the pairs (of any size). Only the groups of two or more are looked at, and only their shapes are made (`shape`).
fn overlaps_with(groups: &[&str], shape: &dyn Fn(usize) -> Mp, inner_of: Option<&dyn Fn(usize) -> Mp>, min_m2: f64) -> (usize, f64) {
    let mut by: BTreeMap<&str, Vec<usize>> = BTreeMap::new();
    for (i, g) in groups.iter().enumerate() {
        by.entry(g).or_default().push(i);
    }
    let (mut n, mut total) = (0, 0.0);
    for ids in by.values().filter(|v| v.len() >= 2) {
        let geoms: Vec<Mp> = ids.iter().map(|&i| shape(i)).collect();
        let index = Index::new(geoms.iter().map(|g| g.bounding_rect()));
        let size: Vec<usize> = geoms.iter().map(|g| g.0.iter().map(|p| p.exterior().0.len() + p.interiors().iter().map(|r| r.0.len()).sum::<usize>()).sum()).collect();
        // (a small shape against a large one is cut by the edges of the large one near it: an overlay with all of them is slow)
        let segs: Vec<std::cell::OnceCell<SegIndex>> = (0..geoms.len()).map(|_| std::cell::OnceCell::new()).collect();
        for i in 0..geoms.len() {
            let Some(r) = geoms[i].bounding_rect() else { continue };
            for j in index.query(&r) {
                if j > i {
                    let (small, big) = if size[i] <= size[j] { (i, j) } else { (j, i) };
                    let a = if size[big] > 200 { ops::area(&ops::clip_by(&geoms[small], segs[big].get_or_init(|| SegIndex::new(&geoms[big])), true)) } else { ops::area(&ops::intersection(&geoms[i], &geoms[j])) };
                    total += a;
                    // (the overlap of the shapes read 1 cm inside their outlines is never more than this one: only a pair that passes it is measured so)
                    let a = match inner_of {
                        Some(f) if a > min_m2 => ops::area(&ops::intersection(&f(ids[i]), &f(ids[j]))),
                        _ => a,
                    };
                    if a > min_m2 {
                        n += 1;
                    }
                }
            }
        }
    }
    (n, total)
}

fn overlaps(groups: &[&str], geoms: &[Mp], min_m2: f64) -> usize {
    overlaps_with(groups, &|i| geoms[i].clone(), None, min_m2).0
}

pub fn partitions(inp: &Input) -> Vec<Check> {
    let mut out = Vec::new();
    let mut lap = urbanstyle_geo::Lap::new("checks");
    let unit_ids: BTreeSet<&str> = inp.units.iter().map(|u| u.id.as_str()).collect();

    // ---- U1-U7: the spaces (rank 3)
    let ug: Vec<Mp> = inp.units.iter().map(|u| inner(&u.geom)).collect();
    let levels: Vec<String> = inp.units.iter().map(|u| u.level.to_string()).collect();
    let lv: Vec<&str> = levels.iter().map(String::as_str).collect();
    out.push(check("U1", true, overlaps(&lv, &ug, 0.05), "spaces overlapping by more than 0.05 m2 (rank 3 partitions the street; the lon/lat storage leaves hairlines under that)"));
    let bad = inp.units.iter().filter(|u| u.geom.0.len() != 1 || !geo::Validation::is_valid(&u.geom)).count();
    out.push(check("U2", true, bad, "spaces invalid, empty or in more than one part"));
    let no_unit: BTreeSet<&str> = inp.junctions.iter().map(|j| j.intersection.as_str()).filter(|i| !unit_ids.contains(i)).collect();
    out.push(check("U3", true, no_unit.len(), "junctions with no intersection space"));
    // the junction nodes: (intersection, level, point), each once
    let mut jn: BTreeSet<(String, i32, i64)> = BTreeSet::new();
    for j in &inp.junctions {
        if inp.node_pt.contains_key(&j.node) {
            jn.insert((j.intersection.clone(), j.level, j.node));
        }
    }
    let by_id: HashMap<&str, usize> = inp.units.iter().enumerate().map(|(i, u)| (u.id.as_str(), i)).collect();
    let (mut u4, mut u5) = (0, 0);
    let sub_idx: Vec<SegIndex> = ug.iter().map(SegIndex::new).collect();
    for (i_, l, n) in &jn {
        let p = inp.node_pt[n];
        if let Some(&k) = by_id.get(i_.as_str()) {
            if Euclidean.distance(&ug[k], &geo::Point::from(p)) > 0.5 {
                u4 += 1;
            }
        }
        for (k, u) in inp.units.iter().enumerate() {
            if u.kind == "subsection" && u.level == *l && sub_idx[k].contains(p) {
                u5 += 1;
            }
        }
    }
    out.push(check("U4", true, u4, "junction nodes outside their own intersection space (> 0.5 m)"));
    out.push(check("U5", true, u5, "junction nodes inside a road's space"));
    let mut u6 = 0;
    for s in &inp.subsections {
        let Some(ln) = &s.line else { continue };
        for (k, u) in inp.units.iter().enumerate() {
            if matches!(u.kind.as_str(), "intersection" | "roundabout") && u.level == s.level && sub_idx[k].clip_line(ln, true).iter().map(lines::length).sum::<f64>() > 1.0 {
                u6 += 1;
            }
        }
    }
    out.push(check("U6", true, u6, "subsection lines reaching more than 1 m into an intersection"));
    let sub_ids: BTreeSet<&str> = inp.subsections.iter().map(|s| s.id.as_str()).collect();
    out.push(check("U7", true, sub_ids.iter().filter(|s| !unit_ids.contains(*s)).count(), "subsections with no space"));

    lap.lap("spaces U1-U7");
    // ---- U8, U9: the parts of a space cover it exactly
    let mut part_area: HashMap<&str, f64> = HashMap::new();
    for p in &inp.parts {
        *part_area.entry(p.unit.as_str()).or_insert(0.0) += ops::area(&p.geom);
    }
    let u8n = inp.units.iter().filter(|u| {
        let a = ops::area(&u.geom);
        (a - part_area.get(u.id.as_str()).copied().unwrap_or(0.0)).abs() > (0.03 * a).max(1.5)
    }).count();
    out.push(check("U8", true, u8n, "spaces whose parts do not add up to them (3% or 1.5 m2)"));
    let pu: Vec<&str> = inp.parts.iter().map(|p| p.unit.as_str()).collect();
    out.push(check("U9", true, overlaps_with(&pu, &|i| ops::orient(&inp.parts[i].geom), Some(&|i| inner(&inp.parts[i].geom)), 0.05).0, "parts of one space overlapping by more than 0.05 m2 (rank 5 partitions the space)"));

    lap.lap("parts U8-U9");
    // ---- U11-U13: the lanes into each junction
    out.push(check("U11", false, inp.approaches.iter().filter(|a| a.moves == Some(0)).count(), "lanes entering a junction with no move at all"));
    let inter: BTreeSet<&str> = inp.units.iter().filter(|u| u.kind == "intersection").map(|u| u.id.as_str()).collect();
    let mut straight: BTreeMap<(&str, Option<&str>), bool> = BTreeMap::new();
    for a in inp.approaches.iter().filter(|a| a.moves.map_or(false, |m| m > 0) && inter.contains(a.unit.as_str())) {
        let e = straight.entry((a.unit.as_str(), a.from_edge.as_deref())).or_insert(false);
        *e |= a.ways.as_deref().map_or(false, |w| w.contains("straight"));
    }
    let mut per_unit: BTreeMap<&str, usize> = BTreeMap::new();
    for (u, _) in straight.keys() {
        *per_unit.entry(u).or_insert(0) += 1;
    }
    let u12 = straight.iter().filter(|((u, _), s)| !**s && per_unit[u] >= 4).count();
    out.push(check("U12", false, u12, "approaches with no straight move for all traffic, at junctions of 4+ approaches"));
    let u13 = inp.approaches.iter().filter(|a| a.arrow == Some(false) && matches!(a.no_arrow_because.as_deref(), Some("lane piece under 4 m") | Some("another arrow in the way"))).count();
    out.push(check("U13", false, u13, "lanes with a move for all traffic but no turn arrow (a lane piece under 4 m, another arrow in the way)"));

    lap.lap("approaches");
    // ---- G1-G3: the ground (rank 1) partitions the area
    let unknown: Vec<&GroundIn> = inp.ground.iter().filter(|g| g.typ == "unknown").collect();
    let unknown_m2: f64 = unknown.iter().map(|g| ops::area(&g.geom)).sum();
    out.push(check("G1", false, unknown.len(), format!("pieces of ground of no known kind ({unknown_m2:.0} m2)")));
    // (G3 from the areas: the ground items do not overlap but by hairlines (G2), so the union is their areas less their overlaps)
    let gl: Vec<String> = inp.ground.iter().map(|g| g.level.to_string()).collect();
    let (g2, g_overlap) = overlaps_with(&gl.iter().map(String::as_str).collect::<Vec<_>>(), &|i| ops::orient(&inp.ground[i].geom), None, 0.05);
    let ground_area: f64 = inp.ground.iter().map(|g| ops::area(&g.geom)).sum();
    let gap = ops::area(&inp.area) - (ground_area - g_overlap);
    if std::env::var("URBANSTYLE_COUNTS").is_ok() {
        eprintln!("COUNT G3 gap {gap:.3} m2 (area {:.1}, ground {ground_area:.1}, overlaps {g_overlap:.3})", ops::area(&inp.area));
    }
    out.push(check("G3", true, (gap > 1.0) as usize, "the ground's kinds leave a gap: the area less their union, over 1 m2 in all (rank 1 partitions rank 0; hairlines of the lon/lat storage under that)"));
    out.push(check("G2", true, g2, "ground items overlapping by more than 0.05 m2 (the kinds partition the area; the lon/lat storage leaves hairlines under that)"));
    lap.lap("ground G1-G3");

    // ---- L1, L2: the surfaces cover their ground item and do not overlap
    let mut sa: HashMap<&str, f64> = HashMap::new();
    for s in &inp.surfaces {
        *sa.entry(s.ground.as_str()).or_insert(0.0) += ops::area(&s.geom);
    }
    let l1 = inp.ground.iter().filter(|g| {
        let a = ops::area(&g.geom);
        (a - sa.get(g.id.as_str()).copied().unwrap_or(0.0)).abs() > (0.03 * a).max(1.5)
    }).count();
    out.push(check("L1", true, l1, "ground items whose surfaces do not cover them (3% or 1.5 m2)"));
    let sk: Vec<&str> = inp.surfaces.iter().map(|s| s.ground.as_str()).collect();
    out.push(check("L2", true, overlaps_with(&sk, &|i| ops::orient(&inp.surfaces[i].geom), Some(&|i| inner(&inp.surfaces[i].geom)), 0.5).0, "surfaces of one ground item overlapping by more than 0.5 m2"));

    lap.lap("surfaces L1-L2");
    // ---- B1, B7, B8: the blocks
    let area = ops::orient(&inp.area);
    let bks: Vec<Mp> = inp.blocks.iter().map(|b| ops::orient(&b.geom)).collect();
    let bk_idx = Index::new(bks.iter().map(|g| g.bounding_rect()));
    // (a small shape against a block of thousands of edges: cut by the edges near it, `ops::clip_by`)
    let bk_seg: Vec<SegIndex> = bks.iter().map(SegIndex::new).collect();
    let area_seg = SegIndex::new(&area);
    let (mut b1, mut b1m2) = (0usize, 0.0);
    for b in &inp.buildings {
        let g = ops::clip_by(&ops::orient(b), &area_seg, true);
        let Some(r) = g.bounding_rect() else { continue };
        let ga = ops::area(&g);
        for k in bk_idx.query(&r) {
            let inside = ops::area(&ops::clip_by(&g, &bk_seg[k], true));
            if inside > 1.0 && ga - inside > 1.0 {
                b1 += 1;
                b1m2 += ga - inside;
            }
        }
    }
    out.push(check("B1", false, b1, format!("buildings reaching over a block's edge ({b1m2:.0} m2 outside their block; drawn whole)")));
    lap.lap("B1");
    let (mut b7, mut b7m2) = (0usize, 0.0);
    for u in inp.units.iter().filter(|u| u.level == 0) {
        let g = ops::orient(&u.geom);
        let Some(r) = g.bounding_rect() else { continue };
        for k in bk_idx.query(&r) {
            let a = ops::area(&ops::buffer(&ops::clip_by(&g, &bk_seg[k], true), -0.02));
            if a > 0.05 {
                b7 += 1;
                b7m2 += a;
            }
        }
    }
    out.push(check("B7", true, b7, format!("street spaces reaching into a block by over 0.05 m2 past a 2 cm hairline ({b7m2:.1} m2 in all): every space is cut from rank 1's street")));
    lap.lap("B7");
    let narrowed: Vec<&PartIn> = inp.parts.iter().filter(|p| p.level == 0 && p.typ == "lane" && p.width_method.as_deref() == Some("narrowed")).collect();
    let units_n: BTreeSet<&str> = narrowed.iter().map(|p| p.unit.as_str()).collect();
    out.push(check("B8", false, units_n.len(), format!("spaces whose lanes narrowed to fit between the street's edges ({} lane parts; the count as OSM maps it, down to 2.75 m)", narrowed.len())));
    out
}

/// The numbers this crate chooses, for the manifest `urban.meta` (`chosen.<name>`): name, value, what it is.
pub fn chosen() -> Vec<(String, f64, String)> {
    vec![
        ("checks.W1_M".to_string(), roadway::W1_M, "a road line this long or more between two pieces of roadway with no roadway under it".to_string()),
        ("checks.W2_M".to_string(), roadway::W2_M, "at a joint, the roadway's ends on the two sides differ by this or more".to_string()),
        ("checks.W3_M".to_string(), roadway::W3_M, "at a node where roads of two levels meet, each level's roadway comes this near the node".to_string()),
    ]
}
