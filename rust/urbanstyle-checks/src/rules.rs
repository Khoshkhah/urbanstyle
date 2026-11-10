//! The street rules (docs/design/street-rules.md) at level 0, as `checks.rule_checks` reads them: A2, A3, J1, J2, J3, K2, M1, X1. Not ported:
//! A1 (the lanes on their OSM line: 0 in every build, a guarantee of SimReady's lanes), K1 (a city's catch basins) and J4 (`work.change`).
use crate::{check, Check, Input, RoadIn};
use geo::{BoundingRect, Coord, Distance, Euclidean, LineString, Point, Rect};
use std::collections::{BTreeMap, BTreeSet};
use urbanstyle_geo::index::{Index, NearIndex, SegIndex};
use urbanstyle_geo::lines;
use urbanstyle_geo::ops::{self, Mp};

/// A road between two junction nodes whose OSM line stays this near the straight line between its ends is drawn straight (`network.STRAIGHT_M`).
const STRAIGHT_M: f64 = 2.0;
/// A road between two junction nodes shorter than this (or any `_link`) is a connector (`network.CONNECTOR_M`).
const CONNECTOR_M: f64 = 40.0;
/// A crossing piece over the roadway longer than this runs along the road, not across it (`network.XWALK_MAX_M`).
const XWALK_MAX_M: f64 = 40.0;
const ROAD_T: [&str; 11] = ["lane", "junction area", "paved", "bridge deck", "bus lane", "bus zone", "parking", "shoulder", "cycle lane", "crosswalk", "cycle crossing"];

fn pt(c: Coord<f64>) -> Point<f64> {
    Point::from(c)
}

fn grow(r: Rect<f64>, d: f64) -> Rect<f64> {
    Rect::new(Coord { x: r.min().x - d, y: r.min().y - d }, Coord { x: r.max().x + d, y: r.max().y + d })
}

/// The line as the straight line between its ends where it stays within `STRAIGHT_M` of it, else itself (`network.straight`).
fn straight(ln: LineString<f64>) -> LineString<f64> {
    let (a, b) = (ln.0[0], *ln.0.last().unwrap());
    let chord = (a.x - b.x).hypot(a.y - b.y);
    let hd = ln.0.iter().map(|p| dist_seg(*p, a, b)).fold(0.0, f64::max);
    if chord > 0.5 && hd <= STRAIGHT_M {
        LineString::new(vec![a, b])
    } else {
        ln
    }
}

fn dist_seg(p: Coord<f64>, a: Coord<f64>, b: Coord<f64>) -> f64 {
    let (dx, dy) = (b.x - a.x, b.y - a.y);
    let l2 = dx * dx + dy * dy;
    let t = if l2 > 0.0 { (((p.x - a.x) * dx + (p.y - a.y) * dy) / l2).clamp(0.0, 1.0) } else { 0.0 };
    (p.x - a.x - t * dx).hypot(p.y - a.y - t * dy)
}

fn len_in(idx: &SegIndex, l: &LineString<f64>, inside: bool) -> f64 {
    idx.clip_line(l, inside).iter().map(lines::length).sum()
}

/// The lines of one OSM way, joined (`line_merge(union_all(...))`).
fn way_lines(roads: &[&RoadIn]) -> BTreeMap<i64, Vec<LineString<f64>>> {
    let mut by: BTreeMap<i64, Vec<LineString<f64>>> = BTreeMap::new();
    for r in roads {
        if let Some(l) = &r.line {
            by.entry(r.osm_id).or_default().push(l.clone());
        }
    }
    by.into_iter().map(|(k, v)| (k, lines::dissolve(v))).collect()
}

pub fn rules(inp: &Input) -> Vec<Check> {
    let mut lap = urbanstyle_geo::Lap::new("checks");
    let mut out = Vec::new();
    let parts: Vec<&crate::PartIn> = inp.parts.iter().filter(|p| p.level == 0).collect();
    let area_full = ops::orient(&inp.area);
    let area2 = SegIndex::new(&ops::buffer(&area_full, -2.0));
    let roads: Vec<&RoadIn> = inp.roads.iter().filter(|r| r.level == 0 && r.street && matches!(r.typ.as_str(), "road" | "walkway") && r.line.is_some()).collect();
    let raw = way_lines(&roads);
    let class_of: BTreeMap<i64, Option<String>> = roads.iter().map(|r| (r.osm_id, r.class.clone())).collect();

    // ---- the junction nodes as the rules read them: an end of a road line where 3 or more road ends meet (a road through counts 2)
    let road_idx = Index::new(roads.iter().map(|r| r.line.as_ref().unwrap().bounding_rect()));
    let deg = |p: Coord<f64>| -> i32 {
        road_idx
            .query(&grow(Rect::new(p, p), 0.5))
            .into_iter()
            .map(|k| roads[k].line.as_ref().unwrap())
            .filter(|ln| Euclidean.distance(*ln, &pt(p)) <= 0.5)
            .map(|ln| {
                let s = lines::project(ln, p);
                if s < 0.5 || s > lines::length(ln) - 0.5 {
                    1
                } else {
                    2
                }
            })
            .sum()
    };
    let jpts: Vec<Coord<f64>> = roads.iter().flat_map(|r| {
        let l = r.line.as_ref().unwrap();
        [l.0[0], *l.0.last().unwrap()]
    }).filter(|p| deg(*p) >= 3).collect();
    let jidx = Index::new(jpts.iter().map(|p| Some(Rect::new(*p, *p))));
    // each way as network.py draws it: cut at its junction nodes, a piece within STRAIGHT_M of straight drawn straight
    let drawn: BTreeMap<i64, Vec<LineString<f64>>> = raw
        .iter()
        .map(|(o, ls)| {
            let mut v = Vec::new();
            for q in ls {
                let mut cuts: Vec<f64> = vec![0.0, lines::length(q)];
                if let Some(r) = q.bounding_rect() {
                    for k in jidx.query(&grow(r, 0.6)) {
                        if Euclidean.distance(q, &pt(jpts[k])) < 0.6 {
                            cuts.push(lines::project(q, jpts[k]));
                        }
                    }
                }
                cuts.sort_by(|a, b| a.partial_cmp(b).unwrap());
                cuts.dedup();
                for w in cuts.windows(2) {
                    if w[1] - w[0] >= 0.5 {
                        v.push(straight(lines::substring(q, w[0], w[1])));
                    }
                }
            }
            (*o, if v.is_empty() { ls.clone() } else { v })
        })
        .collect();
    lap.lap("junction nodes");

    // ---- A2: a parking or cycle lane that no real source gives
    let a2 = parts.iter().filter(|p| matches!(p.typ.as_str(), "parking" | "cycle lane") && p.source.as_deref().unwrap_or("") == "urbanstyle").count();
    out.push(check("A2", true, a2, "parking or cycle lanes with no real source (source urbanstyle)"));

    // ---- A3: a stretch of a road line over 2 m with no roadway under it, inside the area
    let cover0 = ops::union_all(parts.iter().filter(|p| ROAD_T.contains(&p.typ.as_str())).map(|p| ops::orient(&p.geom)).collect::<Vec<_>>().iter());
    let cover_idx = SegIndex::new(&ops::buffer(&cover0, 0.3));
    let mut a3 = 0;
    for r in roads.iter().filter(|r| !matches!(r.class.as_deref(), None | Some("pedestrian"))) {
        let Some(ds) = drawn.get(&r.osm_id) else { continue };
        let near = NearIndex::new(std::iter::once(r.line.as_ref().unwrap()));
        let pieces = lines::merge(near.pieces_within(ds.iter(), 3.0));
        for q in pieces {
            for in_area in area2.clip_line(&q, true) {
                for bare in cover_idx.clip_line(&in_area, false) {
                    if lines::length(&bare) > 2.0 {
                        a3 += 1;
                    }
                }
            }
        }
    }
    out.push(check("A3", true, a3, "stretches of a road line over 2 m with no roadway under it"));
    lap.lap("A3");

    // ---- J1: an intersection with no junction node in it
    let mut j1 = 0;
    for u in inp.units.iter().filter(|u| u.level == 0 && u.kind == "intersection") {
        let g = ops::orient(&u.geom);
        let idx = SegIndex::new(&g);
        let Some(r) = g.bounding_rect() else { continue };
        if !jidx.query(&grow(r, 0.5)).into_iter().any(|k| idx.distance(jpts[k]) <= 0.5) {
            j1 += 1;
        }
    }
    out.push(check("J1", true, j1, "intersections with no junction node (3 or more road ends)"));

    // ---- J2: a junction area reaching over 40 m2 (and a tenth of its area) outside its arms' bands
    let extend = |ln: &LineString<f64>| -> LineString<f64> {
        let p = &ln.0;
        let dir = |a: Coord<f64>, b: Coord<f64>| {
            let h = (b.x - a.x).hypot(b.y - a.y);
            let h = if h == 0.0 { 1.0 } else { h };
            ((b.x - a.x) / h, (b.y - a.y) / h)
        };
        let (d0, d1) = (dir(p[0], p[1]), dir(p[p.len() - 2], p[p.len() - 1]));
        let mut v = vec![Coord { x: p[0].x - d0.0 * 25.0, y: p[0].y - d0.1 * 25.0 }];
        v.extend(p.iter().copied());
        v.push(Coord { x: p[p.len() - 1].x + d1.0 * 25.0, y: p[p.len() - 1].y + d1.1 * 25.0 });
        LineString::new(v)
    };
    let mut bands: Vec<Mp> = Vec::new();
    for s in inp.subsections.iter().filter(|s| s.level == 0) {
        if let (Some(l), Some(w)) = (&s.line, s.width) {
            if l.0.len() >= 2 {
                bands.push(ops::buffer_line_flat(&extend(l), w / 2.0 + 2.5));
            }
        }
    }
    for r in inp.roads.iter().filter(|r| r.level == 0 && r.typ == "road" && r.street) {
        if let (Some(l), Some(w)) = (&r.line, r.width) {
            if l.0.len() >= 2 {
                bands.push(ops::buffer_line_flat(&extend(l), w / 2.0 + 2.5));
            }
        }
    }
    let band_idx = SegIndex::new(&ops::union_all(bands.iter()));
    let j2 = parts.iter().filter(|p| p.typ == "junction area").filter(|p| {
        let g = ops::orient(&p.geom);
        let limit = 40.0f64.max(0.1 * ops::area(&g));
        ops::clip_by(&g, &band_idx, false).0.iter().any(|q| geo::Area::unsigned_area(q) > limit)
    }).count();
    out.push(check("J2", true, j2, "junction areas reaching over 40 m2 (and a tenth of their area) outside their arms' bands"));
    lap.lap("J1, J2");

    // ---- X1: a crossing way over the roadway with no crosswalk part on it
    let xw_parts: Vec<Mp> = parts.iter().filter(|p| matches!(p.typ.as_str(), "crosswalk" | "cycle crossing")).map(|p| ops::orient(&p.geom)).collect();
    let xw_u = SegIndex::new(&ops::buffer(&ops::union_all(xw_parts.iter()), 0.3));
    let cover0_idx = SegIndex::new(&cover0);
    let mut xways: BTreeMap<i64, Vec<LineString<f64>>> = BTreeMap::new();
    for r in inp.roads.iter().filter(|r| r.level == 0 && matches!(r.typ.as_str(), "walkway" | "cycleway") && r.subtype.as_deref() == Some("crossing")) {
        if let Some(l) = &r.line {
            xways.entry(r.osm_id).or_default().push(l.clone());
        }
    }
    let mut x1 = 0;
    for gs in xways.values() {
        let gs = lines::dissolve(gs.clone());
        let over = |idx: &SegIndex, ls: &[LineString<f64>]| -> Vec<LineString<f64>> { ls.iter().flat_map(|l| idx.clip_line(l, true)).collect() };
        let total = |ls: &[LineString<f64>]| -> f64 { ls.iter().map(lines::length).sum() };
        if total(&over(&area2, &over(&cover_idx, &gs))) > XWALK_MAX_M {
            continue;
        }
        let x = over(&area2, &over(&cover0_idx, &gs));
        let xl = total(&x);
        if xl > 1.0 && xl - total(&over(&xw_u, &x)) > 1.0f64.max(0.2 * xl) {
            x1 += 1;
        }
    }
    out.push(check("X1", true, x1, "crossing ways over the roadway with no crosswalk part on them"));
    lap.lap("X1");

    // ---- M1: a lane line, or a centre line with a real source, where the lane count is chosen
    let chosen: BTreeSet<&str> = parts.iter().filter(|p| p.typ == "lane" && p.source.as_deref() == Some("urbanstyle")).map(|p| p.unit.as_str()).collect();
    let m1 = inp.marks.iter().filter(|m| matches!(m.typ.as_str(), "centre line" | "lane line") && chosen.contains(m.unit.as_str()) && (m.typ == "lane line" || m.source.as_deref() != Some("urbanstyle"))).count();
    out.push(check("M1", true, m1, "lane lines, or centre lines with a real source, where the lane count is chosen"));

    // ---- K2: a loose kerb end touches no other kerb and no crosswalk within 0.3 m
    let kerbs: Vec<&LineString<f64>> = inp.marks.iter().filter(|m| m.typ == "kerb" && m.lines.len() == 1).map(|m| &m.lines[0]).collect();
    let kidx = Index::new(kerbs.iter().map(|l| l.bounding_rect()));
    let xw_idx = Index::new(xw_parts.iter().map(|g| g.bounding_rect()));
    let service: Vec<&LineString<f64>> = inp.roads.iter().filter(|r| r.level == 0 && matches!(r.typ.as_str(), "road" | "walkway") && r.class.as_deref() == Some("service") && !r.street).filter_map(|r| r.line.as_ref()).collect();
    let sidx = Index::new(service.iter().map(|l| l.bounding_rect()));
    let mut k2 = 0;
    for (i, g) in kerbs.iter().enumerate() {
        for p in [g.0[0], *g.0.last().unwrap()] {
            let r = Rect::new(p, p);
            let touches = kidx.query(&grow(r, 0.3)).into_iter().any(|k| k != i && Euclidean.distance(kerbs[k], &pt(p)) < 0.3);
            if touches
                || xw_idx.query(&grow(r, 0.3)).into_iter().any(|k| Euclidean.distance(&xw_parts[k], &pt(p)) < 0.3)
                || sidx.query(&grow(r, 3.0)).into_iter().any(|k| Euclidean.distance(service[k], &pt(p)) < 3.0)
                || !area2.contains(p)
            {
                continue;
            }
            k2 += 1;
        }
    }
    out.push(check("K2", false, k2, "loose kerb ends (not at another kerb, a crosswalk, an alley's mouth or the area's edge)"));
    lap.lap("M1, K2");

    // ---- J3: every connector lies in an intersection, or on a bridge deck
    let jn_pts: Vec<Coord<f64>> = {
        let mut seen: BTreeSet<i64> = BTreeSet::new();
        inp.junctions.iter().filter(|j| j.level == 0 && seen.insert(j.node)).filter_map(|j| inp.node_pt.get(&j.node).copied()).collect()
    };
    let jn_idx = Index::new(jn_pts.iter().map(|p| Some(Rect::new(*p, *p))));
    let c_geoms: Vec<Mp> = inp.units.iter().filter(|u| u.level == 0 && u.kind == "intersection").map(|u| ops::orient(&u.geom)).chain(parts.iter().filter(|p| p.typ == "bridge deck").map(|p| ops::orient(&p.geom))).collect();
    let cover_c = ops::buffer(&ops::union_all(c_geoms.iter()), 0.5);
    let s_geoms: Vec<Mp> = inp.units.iter().filter(|u| u.level == 0 && u.kind != "intersection").map(|u| ops::orient(&u.geom)).collect();
    let cover_s = ops::buffer(&ops::union_all(s_geoms.iter()), 0.5);
    let cover_c_idx = SegIndex::new(&cover_c);
    let cover_cs_idx = SegIndex::new(&ops::union(&cover_c, &cover_s));
    let at_n = |p: Coord<f64>| jn_idx.query(&grow(Rect::new(p, p), 0.6)).into_iter().any(|k| (jn_pts[k].x - p.x).hypot(jn_pts[k].y - p.y) < 0.6);
    let mut j3 = 0;
    for (o, ls) in &raw {
        let link = class_of.get(o).and_then(|c| c.as_deref()).map_or(false, |c| c.ends_with("_link"));
        for q in ls {
            let len = lines::length(q);
            let mut cuts: Vec<f64> = vec![0.0, len];
            if let Some(r) = q.bounding_rect() {
                for k in jn_idx.query(&grow(r, 0.6)) {
                    if Euclidean.distance(q, &pt(jn_pts[k])) < 0.6 {
                        cuts.push(lines::project(q, jn_pts[k]));
                    }
                }
            }
            cuts.sort_by(|a, b| a.partial_cmp(b).unwrap());
            cuts.dedup();
            for w in cuts.windows(2) {
                let pc = lines::substring(q, w[0], w[1]);
                let l = lines::length(&pc);
                if l < 0.5 || pc.0.len() < 2 || !(at_n(pc.0[0]) && at_n(*pc.0.last().unwrap())) {
                    continue;
                }
                if (l < CONNECTOR_M || link) && len_in(&area2, &pc, true) >= l - 1e-9 {
                    let idx = if link { &cover_c_idx } else { &cover_cs_idx };
                    if len_in(idx, &pc, false) > 1.0 {
                        j3 += 1;
                    }
                }
            }
        }
    }
    out.push(check("J3", true, j3, "roads between two junction nodes outside the spaces: a `_link` not inside an intersection, a road under 40 m inside neither an intersection nor a section"));
    lap.lap("J3");
    out
}
