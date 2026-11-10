//! The roadway checks (group 2a): R2, R3, W1, W3. The roadway is one surface along every road of a level (W1), the levels join where
//! streets of two levels meet (W3), SUMO's guide lines stay on the roadway (R2), and OSM's lanes fit between our kerbs (R3).
use crate::{check, Check, Input};
use geo::{BoundingRect, Coord, Distance, Euclidean, LineString, Point};
use std::collections::{BTreeMap, BTreeSet};
use urbanstyle_geo::index::{Index, SegIndex};
use urbanstyle_geo::lines;
use urbanstyle_geo::ops::{self, Mp};

/// The roadway: the carriageway's parts.
pub const ROAD_PARTS: [&str; 13] = ["lane", "paved", "junction area", "ring", "bus lane", "bus zone", "cycle lane", "shoulder", "parking", "no parking", "crosswalk", "cycle crossing", "bridge deck"];
/// R2: the parts that guide lines may run on.
const GUIDE_PARTS: [&str; 9] = ["lane", "shoulder", "parking", "bus zone", "cycle lane", "junction area", "paved", "crosswalk", "cycle crossing"];
/// W1: a road line this long or more between two pieces of roadway with no roadway under it.
pub const W1_M: f64 = 0.1;
/// W3: at a node where roads of two levels meet, each level's roadway comes this near the node.
pub const W3_M: f64 = 0.5;

fn len_in(idx: &SegIndex, l: &LineString<f64>, inside: bool) -> f64 {
    idx.clip_line(l, inside).iter().map(lines::length).sum()
}

pub fn roadway(inp: &Input) -> Vec<Check> {
    let mut out = Vec::new();
    let mut lap = urbanstyle_geo::Lap::new("checks");

    // ---- R2: the guide lines leave the roadway by more than 0.5 m
    let rw2: Vec<Mp> = inp.parts.iter().filter(|p| p.level == 0 && GUIDE_PARTS.contains(&p.typ.as_str())).map(|p| ops::buffer(&ops::orient(&p.geom), 0.1)).collect();
    let rw2 = SegIndex::new(&ops::union_all(rw2.iter()));
    let r2 = inp.guides.iter().filter(|(lv, _)| *lv == 0).filter(|(_, ls)| ls.iter().map(|l| len_in(&rw2, l, false)).sum::<f64>() > 0.5).count();
    out.push(check("R2", false, r2, "guide lines (SUMO's moves) leaving the roadway by more than 0.5 m"));
    // ---- R3: OSM's lane count does not fit between our kerbs
    let r3: BTreeSet<&str> = inp.parts.iter().filter(|p| p.level == 0 && p.typ == "lane" && p.source.as_deref() == Some("osm") && p.width.map_or(false, |w| w < 2.75)).map(|p| p.unit.as_str()).collect();
    out.push(check("R3", false, r3.len(), "subsections where OSM's lane count does not fit between our kerbs (a lane under 2.75 m): our kerb is probably wrong"));
    lap.lap("R2, R3");

    // ---- W1: the pieces of the roadway of a level meet along every street
    let mut levels: Vec<i32> = inp.parts.iter().map(|p| p.level).collect();
    levels.sort();
    levels.dedup();
    let area1 = SegIndex::new(&ops::buffer(&ops::orient(&inp.area), -1.0));
    let mut w1 = 0;
    for &lv in &levels {
        let parts: Vec<Mp> = inp.parts.iter().filter(|p| p.level == lv && ROAD_PARTS.contains(&p.typ.as_str())).map(|p| ops::orient(&p.geom)).collect();
        let rw = ops::union_all(parts.iter().map(|g| ops::buffer(g, 0.02)).collect::<Vec<_>>().iter());
        let rw_idx = SegIndex::new(&rw);
        for r in inp.roads.iter().filter(|r| r.street && r.typ == "road" && r.level == lv) {
            let Some(ln) = &r.line else { continue };
            let (first, last) = (ln.0[0], *ln.0.last().unwrap());
            for g in rw_idx.clip_line(ln, false) {
                if lines::length(&g) < W1_M || len_in(&area1, &g, false) > 0.0 || len_in(&area1, &g, true) < lines::length(&g) - 1e-9 {
                    continue;
                }
                let (a, b) = (g.0[0], *g.0.last().unwrap());
                let d = |p: Coord<f64>, q: Coord<f64>| (p.x - q.x).hypot(p.y - q.y);
                if rw_idx.distance(a) > 0.05 || rw_idx.distance(b) > 0.05 || d(a, first).min(d(a, last)) < 0.05 || d(b, first).min(d(b, last)) < 0.05 {
                    continue; // (the road's own end, or a stretch off the roadway at one side)
                }
                let len = lines::length(&g);
                let Some(mid) = lines::interpolate(&g, len / 2.0) else { continue };
                let s = lines::project(ln, mid);
                let (p0, p1) = (lines::interpolate(ln, (s - 1.0).max(0.0)).unwrap(), lines::interpolate(ln, (s + 1.0).min(lines::length(ln))).unwrap());
                let (dx, dy) = (p1.x - p0.x, p1.y - p0.y);
                let h = dx.hypot(dy);
                let h = if h == 0.0 { 1.0 } else { h };
                let hits = [1.0, -1.0]
                    .iter()
                    .filter(|&&k| {
                        let seg = LineString::new(vec![mid, Coord { x: mid.x - k * dy / h * 3.0, y: mid.y + k * dx / h * 3.0 }]);
                        len_in(&rw_idx, &seg, true) > 0.0 || rw_idx.contains(seg.0[1])
                    })
                    .count();
                if hits == 1 {
                    continue; // (the line runs along a kerb, roadway on one side only)
                }
                w1 += 1;
            }
        }
    }
    out.push(check("W1", true, w1, format!("stretches of a road line ({W1_M} m or more) between two pieces of roadway with none under it, on any level: the pieces do not meet")));
    lap.lap("W1");

    // ---- W3: where streets of two levels meet, the roadway of each level reaches the node
    let mut ends: BTreeMap<i64, Vec<(i32, i64, Coord<f64>)>> = BTreeMap::new();
    for r in inp.roads.iter().filter(|r| r.street && r.typ == "road") {
        let Some(ln) = &r.line else { continue };
        if let Some(s) = r.src {
            ends.entry(s).or_default().push((r.level, r.osm_id, ln.0[0]));
        }
        if let Some(d) = r.dst {
            ends.entry(d).or_default().push((r.level, r.osm_id, *ln.0.last().unwrap()));
        }
    }
    let area5 = SegIndex::new(&ops::buffer(&ops::orient(&inp.area), -5.0));
    let parts_by_level: BTreeMap<i32, Vec<Mp>> = levels.iter().map(|&lv| (lv, inp.parts.iter().filter(|p| p.level == lv && ROAD_PARTS.contains(&p.typ.as_str())).map(|p| p.geom.clone()).collect())).collect();
    let index_by_level: BTreeMap<i32, Index> = parts_by_level.iter().map(|(lv, v)| (*lv, Index::new(v.iter().map(|g| g.bounding_rect())))).collect();
    let near = |lv: i32, p: Coord<f64>| -> bool {
        let (Some(v), Some(ix)) = (parts_by_level.get(&lv), index_by_level.get(&lv)) else { return false };
        let r = geo::Rect::new(Coord { x: p.x - W3_M, y: p.y - W3_M }, Coord { x: p.x + W3_M, y: p.y + W3_M });
        ix.query(&r).into_iter().any(|k| Euclidean.distance(&v[k], &Point::from(p)) <= W3_M)
    };
    let mut w3 = 0;
    for es in ends.values() {
        let lvs: BTreeSet<i32> = es.iter().map(|e| e.0).collect();
        if lvs.len() < 2 || !area5.contains(es[0].2) {
            continue;
        }
        if es.iter().any(|(lv, _, p)| !near(*lv, *p)) {
            w3 += 1;
        }
    }
    out.push(check("W3", true, w3, format!("nodes where streets of two levels meet (a tunnel's entrance, a ramp) and one level's roadway stops more than {W3_M} m short: the levels do not join")));
    lap.lap("W3");
    out
}

/// W2: where two spaces meet across a street, the roadway reaches the joint at the same points from both sides. Returns the count.
pub const W2_M: f64 = 0.2;
/// A joint is a piece of the shared outline that a street line crosses, within this of the crossing.
const ACROSS_REACH_M: f64 = 15.0;
/// Two outlines that run this near each other are one edge (the neighbours of a cut share their vertices).
pub const SHARED_M: f64 = 1e-7;

fn cross(a: Coord<f64>, b: Coord<f64>, c: Coord<f64>, d: Coord<f64>) -> Option<Coord<f64>> {
    let (r, s) = ((b.x - a.x, b.y - a.y), (d.x - c.x, d.y - c.y));
    let den = r.0 * s.1 - r.1 * s.0;
    if den.abs() < 1e-12 {
        return None;
    }
    let (t, u) = (((c.x - a.x) * s.1 - (c.y - a.y) * s.0) / den, ((c.x - a.x) * r.1 - (c.y - a.y) * r.0) / den);
    ((0.0..=1.0).contains(&t) && (0.0..=1.0).contains(&u)).then(|| Coord { x: a.x + t * r.0, y: a.y + t * r.1 })
}

fn dist_point_seg(p: Coord<f64>, a: Coord<f64>, b: Coord<f64>) -> f64 {
    let (dx, dy) = (b.x - a.x, b.y - a.y);
    let l2 = dx * dx + dy * dy;
    let t = if l2 > 0.0 { (((p.x - a.x) * dx + (p.y - a.y) * dy) / l2).clamp(0.0, 1.0) } else { 0.0 };
    (p.x - a.x - t * dx).hypot(p.y - a.y - t * dy)
}

/// The pieces of the outline `jl` that run across a street: over 45 degrees to the street's line where it crosses the outline, and within
/// `ACROSS_REACH_M` of that crossing (`checks.across`).
fn across(jl: &[LineString<f64>], streets: &[&LineString<f64>], street_idx: &Index) -> Vec<LineString<f64>> {
    let mut out: Vec<LineString<f64>> = Vec::new();
    for g in jl {
        let Some(r) = g.bounding_rect() else { continue };
        for j in street_idx.query(&r) {
            let ln = streets[j];
            for ls in ln.lines() {
                for gs in g.lines() {
                    let Some(x) = cross(ls.start, ls.end, gs.start, gs.end) else { continue };
                    let s = lines::project(ln, x);
                    let (a, b) = (lines::interpolate(ln, (s - 1.0).max(0.0)).unwrap(), lines::interpolate(ln, (s + 1.0).min(lines::length(ln))).unwrap());
                    let (d, h) = ((b.x - a.x, b.y - a.y), (b.x - a.x).hypot(b.y - a.y));
                    let h = if h == 0.0 { 1.0 } else { h };
                    for seg in g.lines() {
                        let e = (seg.end.x - seg.start.x, seg.end.y - seg.start.y);
                        let he = e.0.hypot(e.1);
                        let he = if he == 0.0 { 1.0 } else { he };
                        if dist_point_seg(x, seg.start, seg.end) <= ACROSS_REACH_M && (d.0 * e.0 + d.1 * e.1).abs() / (h * he) < (45.0f64).to_radians().cos() {
                            out.push(LineString::new(vec![seg.start, seg.end]));
                        }
                    }
                }
            }
        }
    }
    if out.is_empty() {
        return out;
    }
    lines::dissolve(out)
}

pub fn joints(inp: &Input) -> Vec<Check> {
    let mut lap = urbanstyle_geo::Lap::new("checks");
    let mut levels: Vec<i32> = inp.parts.iter().map(|p| p.level).collect();
    levels.sort();
    levels.dedup();
    let section_of: BTreeMap<&str, &str> = inp.sections.iter().map(|(k, v)| (k.as_str(), v.as_str())).collect();
    let mut w2 = 0;
    for &lv in &levels {
        let units: Vec<&crate::Unit> = inp.units.iter().filter(|u| u.level == lv).collect();
        let geoms: Vec<Mp> = units.iter().map(|u| ops::orient(&u.geom)).collect();
        let boxes: Vec<_> = geoms.iter().map(|g| g.bounding_rect()).collect();
        let uidx = Index::new(boxes.iter().copied());
        let rw: Vec<SegIndex> = {
            let mut by_unit: BTreeMap<&str, Vec<Mp>> = BTreeMap::new();
            for p in inp.parts.iter().filter(|p| p.level == lv && ROAD_PARTS.contains(&p.typ.as_str())) {
                by_unit.entry(p.unit.as_str()).or_default().push(ops::buffer(&ops::orient(&p.geom), 0.02));
            }
            units.iter().map(|u| SegIndex::new(&by_unit.get(u.id.as_str()).map_or(Mp::new(vec![]), |v| ops::union_all(v.iter())))).collect()
        };
        let ring_idx: Vec<urbanstyle_geo::index::NearIndex> = geoms.iter().map(|g| urbanstyle_geo::index::NearIndex::new(g.0.iter().flat_map(|p| std::iter::once(p.exterior()).chain(p.interiors())))).collect();
        let streets: Vec<&LineString<f64>> = inp.roads.iter().filter(|r| r.street && r.typ == "road" && r.level == lv).filter_map(|r| r.line.as_ref()).collect();
        let street_idx = Index::new(streets.iter().map(|l| l.bounding_rect()));
        // (a road's dead end: the end node of a road line that no other road or walkway meets; there the roadway stops)
        let mut deg: BTreeMap<i64, usize> = BTreeMap::new();
        for r in inp.roads.iter().filter(|r| r.level == lv) {
            for n in [r.src, r.dst].into_iter().flatten() {
                *deg.entry(n).or_insert(0) += 1;
            }
        }
        let dead: Vec<Coord<f64>> = inp.roads.iter().filter(|r| r.typ == "road" && r.level == lv).filter_map(|r| r.line.as_ref().map(|l| (r, l))).flat_map(|(r, l)| {
            let mut v = vec![];
            if r.src.map_or(false, |n| deg.get(&n) == Some(&1)) {
                v.push(l.0[0]);
            }
            if r.dst.map_or(false, |n| deg.get(&n) == Some(&1)) {
                v.push(*l.0.last().unwrap());
            }
            v
        }).collect();
        let dead_idx = Index::new(dead.iter().map(|p| Some(geo::Rect::new(*p, *p))));
        for i in 0..units.len() {
            let Some(r) = boxes[i] else { continue };
            for j in uidx.query(&r) {
                if units[j].id <= units[i].id {
                    continue;
                }
                // the shared outline: the pieces of a's outline along b's, joined
                let shared = ring_idx[j].pieces_within(geoms[i].0.iter().flat_map(|p| std::iter::once(p.exterior()).chain(p.interiors())), inp.shared_m);
                if shared.is_empty() {
                    continue;
                }
                let jl = across(&lines::merge(shared), &streets, &street_idx);
                let len: f64 = jl.iter().map(lines::length).sum();
                if jl.is_empty() || len < 0.3 {
                    continue;
                }
                let jr = jl.iter().filter_map(|l| l.bounding_rect()).fold(None::<geo::Rect<f64>>, |a, b| Some(a.map_or(b, |a| geo::Rect::new(Coord { x: a.min().x.min(b.min().x), y: a.min().y.min(b.min().y) }, Coord { x: a.max().x.max(b.max().x), y: a.max().y.max(b.max().y) }))));
                let near_dead = jr.map_or(false, |r| {
                    let grown = geo::Rect::new(Coord { x: r.min().x - 1.0, y: r.min().y - 1.0 }, Coord { x: r.max().x + 1.0, y: r.max().y + 1.0 });
                    dead_idx.query(&grown).into_iter().any(|k| jl.iter().any(|l| Euclidean.distance(l, &Point::from(dead[k])) < 1.0))
                });
                if near_dead {
                    continue;
                }
                let clip = |idx: &SegIndex| -> Vec<LineString<f64>> { jl.iter().flat_map(|l| idx.clip_line(l, true)).collect() };
                let (xa, xb) = (clip(&rw[i]), clip(&rw[j]));
                if xa.is_empty() && xb.is_empty() {
                    continue;
                }
                let (la, lb): (f64, f64) = (xa.iter().map(lines::length).sum(), xb.iter().map(lines::length).sum());
                let near = |from: &[LineString<f64>], to: &[LineString<f64>]| -> f64 {
                    if from.is_empty() || to.is_empty() {
                        return 0.0;
                    }
                    urbanstyle_geo::index::NearIndex::new(to.iter()).length_within(from.iter(), W2_M / 2.0)
                };
                let d = (la - near(&xa, &xb)) + (lb - near(&xb, &xa));
                if d >= W2_M {
                    w2 += 1;
                }
            }
        }
    }
    let _ = section_of;
    lap.lap("W2");
    vec![check("W2", true, w2, format!("joints where the roadway reaches the two sides at points {W2_M} m or more apart, on any level (a step or a sideways shift)"))]
}

/// R4: where two subsections meet, each edge between two roadway items (lanes, cycle lanes, parking) on one side has one on the other. The
/// joint is read every 0.1 m, 0.3 m into each side; a taper (zero width at the joint) has no edge there (`checks.lane_joints`).
pub fn lane_joints(inp: &Input) -> Check {
    const ITEMS: [&str; 4] = ["lane", "cycle lane", "parking", "bus zone"];
    let units: Vec<&crate::Unit> = inp.units.iter().filter(|u| u.level == 0 && u.kind == "subsection").collect();
    let geoms: Vec<Mp> = units.iter().map(|u| ops::orient(&u.geom)).collect();
    let segs: Vec<SegIndex> = geoms.iter().map(SegIndex::new).collect();
    let rings: Vec<urbanstyle_geo::index::NearIndex> = geoms.iter().map(|g| urbanstyle_geo::index::NearIndex::new(g.0.iter().flat_map(|p| std::iter::once(p.exterior()).chain(p.interiors())))).collect();
    let boxes: Vec<_> = geoms.iter().map(|g| g.bounding_rect()).collect();
    let idx = Index::new(boxes.iter().copied());
    let mut parts: Vec<Vec<(String, SegIndex)>> = (0..units.len()).map(|_| Vec::new()).collect();
    let by_id: BTreeMap<&str, usize> = units.iter().enumerate().map(|(i, u)| (u.id.as_str(), i)).collect();
    for p in inp.parts.iter().filter(|p| p.level == 0 && ITEMS.contains(&p.typ.as_str())) {
        if let Some(&i) = by_id.get(p.unit.as_str()) {
            parts[i].push((p.id.clone(), SegIndex::new(&ops::orient(&p.geom))));
        }
    }
    let mut bad = 0usize;
    for u in 0..units.len() {
        let Some(r) = boxes[u] else { continue };
        let grown = geo::Rect::new(Coord { x: r.min().x - 0.1, y: r.min().y - 0.1 }, Coord { x: r.max().x + 0.1, y: r.max().y + 0.1 });
        for v in idx.query(&grown) {
            if units[v].id <= units[u].id || (parts[u].is_empty() && parts[v].is_empty()) {
                continue;
            }
            let pieces = rings[v].pieces_within(geoms[u].0.iter().flat_map(|p| std::iter::once(p.exterior()).chain(p.interiors())), 0.05);
            for seg in lines::merge(pieces) {
                let len = lines::length(&seg);
                if len < 2.0 {
                    continue;
                }
                let mut edges: Vec<Vec<usize>> = Vec::new();
                for w in [u, v] {
                    let mut labs: Vec<Option<&str>> = Vec::new();
                    for k in 0..(len / 0.1) as usize {
                        let d = 0.05 + k as f64 * 0.1;
                        let (p, a, b) = (lines::interpolate(&seg, d).unwrap(), lines::interpolate(&seg, (d - 0.05).max(0.0)).unwrap(), lines::interpolate(&seg, (d + 0.05).min(len)).unwrap());
                        let (nx, ny) = (a.y - b.y, b.x - a.x);
                        let h = nx.hypot(ny);
                        let h = if h == 0.0 { 1.0 } else { h };
                        let mut q = Coord { x: p.x + nx / h * 0.3, y: p.y + ny / h * 0.3 };
                        if !segs[w].contains(q) {
                            q = Coord { x: p.x - nx / h * 0.3, y: p.y - ny / h * 0.3 };
                        }
                        labs.push(parts[w].iter().find(|(_, s)| s.contains(q)).map(|(id, _)| id.as_str()));
                    }
                    edges.push((1..labs.len()).filter(|&k| labs[k] != labs[k - 1]).collect());
                }
                let near = |k: usize, other: &[usize]| other.iter().any(|&x| (k as i64 - x as i64).abs() <= 2);
                bad += edges[0].iter().filter(|&&k| !near(k, &edges[1])).count();
                bad += edges[1].iter().filter(|&&k| !near(k, &edges[0])).count();
            }
        }
    }
    check("R4", false, bad, "edges of lanes, cycle lanes and parking at a joint with no edge on the other side (0.3 m in, within 0.25 m)")
}
