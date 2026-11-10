//! Layer 0, the ground (docs/design/space-layers.md): every piece of the area is exactly one item of one kind. The port of
//! `ground.assemble` of urbanstyle's Python code. The kinds come in an order (`Input::order`) and each takes only the ground the earlier
//! ones left; what is left is traced to a road or a path that runs through it, or joins the neighbour it shares the most edge with, or
//! is a yard (in a block) or unknown; the pieces then partition the area.
//!
//! The inputs are read elsewhere (`ground.gather` in Python: SQL on duckOSM's tables); nothing here reads a database.
use geo::{Area, BoundingRect, Centroid, Coord, Euclidean, InteriorPoint, Length, LineString, Polygon, Rect};
use std::collections::{BTreeMap};
pub mod surfaces;

use urbanstyle_geo::index::{Index, NearIndex, SegIndex};
use urbanstyle_geo::ops::{self, Mp};

/// A piece of ground smaller than this is left to its neighbours.
pub const MIN_M2: f64 = 0.5;
/// Left-over ground smaller than this, or thinner than `SLIVER_W_M` on average (twice its area over its outline), is a sliver.
pub const SLIVER_M2: f64 = 5.0;
pub const SLIVER_W_M: f64 = 2.0;
/// An alley's width where OSM gives none (chosen).
pub const ALLEY_W_M: f64 = 6.0;
/// Two outlines that run within this of each other share an edge.
pub const NEAR_M: f64 = 0.05;
/// A polygon of a ground item under this is a hairline of the cuts: it is no row.
pub const MIN_ROW_M2: f64 = 0.001;
/// A strip of left-over ground thinner than this is a gap between two pieces that touch, not ground.
pub const HAIRLINE_M: f64 = 0.01;
/// Rings joined to items by the slivers step before its big index is built again.
const FRESH_RINGS: usize = 64;

pub struct Item {
    pub r#ref: String,
    pub name: Option<String>,
    pub geom: Mp,
}

/// One kind of ground, with its sources' items in the order they take it.
pub struct Kind {
    pub typ: String,
    pub source: String,
    pub method: String,
    pub items: Vec<Item>,
}

/// A road or path line, to trace the left-over ground to.
pub struct Line {
    pub typ: String,
    pub r#ref: String,
    pub name: Option<String>,
    pub lines: Vec<LineString<f64>>,
    pub width: Option<f64>,
}

pub struct Input {
    pub area: Mp,
    /// The blocks' land; `None` where there are no blocks.
    pub land: Option<Mp>,
    pub has_parcels: bool,
    pub order: Vec<Kind>,
    pub lines: Vec<Line>,
}

#[derive(Clone)]
pub struct Ground {
    pub id: String,
    pub typ: String,
    pub name: Option<String>,
    pub source: String,
    pub method: String,
    pub r#ref: Option<String>,
    pub geom: Polygon<f64>,
}

/// An item before its pieces are separated.
struct Out {
    id: String,
    typ: String,
    name: Option<String>,
    source: String,
    method: String,
    r#ref: Option<String>,
    geom: Mp,
}

fn rings(m: &Mp) -> Vec<&LineString<f64>> {
    m.0.iter().flat_map(|p| std::iter::once(p.exterior()).chain(p.interiors())).collect()
}

fn perimeter(p: &Polygon<f64>) -> f64 {
    std::iter::once(p.exterior()).chain(p.interiors()).map(|r| Euclidean.length(r)).sum()
}

/// Python's `round`: halves go to the even number.
fn round(x: f64) -> i64 {
    x.round_ties_even() as i64
}

fn centroid_id(p: &Mp) -> (i64, i64) {
    p.centroid().map_or((0, 0), |c| (round(c.x()), round(c.y())))
}

/// `g` inside `within`, looking only at the edges of `within` near `g` (`ops::clip_by`).
struct Within {
    index: SegIndex,
}

impl Within {
    fn new(m: &Mp) -> Self {
        Within { index: SegIndex::new(m) }
    }

    fn clip(&self, g: &Mp) -> Mp {
        ops::clip_by(g, &self.index, true)
    }
}

/// The length of the lines `ls` that lies inside the polygon `p`.
fn length_in(idx: &SegIndex, ls: &[LineString<f64>]) -> f64 {
    ls.iter().flat_map(|l| idx.clip_line(l, true)).map(|l| Euclidean.length(&l)).sum()
}

pub fn build(inp: &Input) -> Vec<Ground> {
    let mut lap = urbanstyle_geo::Lap::new("ground");
    let area = &inp.area;
    let land = inp.land.as_ref();
    let area_within = Within::new(area);
    let land_within = land.map(Within::new);

    // ---- the kinds take the ground. One arrangement of every item's outline cuts the area into faces; each face goes to the first item, in
    // the order of the kinds, that covers it. No item waits for another: cutting item after item took the union of all the earlier pieces near
    // each one (7 s of Monaco's 11 s).
    struct Flat<'a> {
        kind: &'a Kind,
        item: &'a Item,
        geom: Mp,
    }
    let mut flat: Vec<Flat> = Vec::new();
    for kind in &inp.order {
        let use_land = land.is_some() && kind.typ != "street" && !(kind.typ == "path" && kind.source == "urbanstyle" && kind.method == "derived");
        let within = if use_land { land_within.as_ref().unwrap() } else { &area_within };
        for item in &kind.items {
            let geom = within.clip(&item.geom);
            if !geom.0.is_empty() {
                flat.push(Flat { kind, item, geom });
            }
        }
    }
    lap.lap("items clipped");
    let outlines: Vec<LineString<f64>> = flat.iter().flat_map(|f| rings(&f.geom).into_iter().cloned()).collect();
    let faces = ops::slice(area, &outlines);
    drop(outlines);
    lap.lap("faces");
    // (a face is covered by an item when a point inside the face is inside the item)
    let boxes = Index::new(flat.iter().map(|f| f.geom.bounding_rect()));
    let tester: Vec<std::cell::OnceCell<SegIndex>> = (0..flat.len()).map(|_| std::cell::OnceCell::new()).collect();
    let mut by_item: Vec<Vec<usize>> = vec![Vec::new(); flat.len()];
    for (fi, f) in faces.0.iter().enumerate() {
        let Some(pt) = f.interior_point() else { continue };
        let c = Coord { x: pt.x(), y: pt.y() };
        for i in boxes.query(&Rect::new(c, c)) {
            if tester[i].get_or_init(|| SegIndex::new(&flat[i].geom)).contains(c) {
                by_item[i].push(fi);
            }
        }
    }
    lap.lap("faces covered");
    // (in the order of the kinds: an item that wins under MIN_M2 takes nothing and leaves its faces to the next)
    let face_area: Vec<f64> = faces.0.iter().map(|f| f.unsigned_area()).collect();
    let mut owner: Vec<Option<usize>> = vec![None; faces.0.len()];
    let mut won: Vec<Vec<usize>> = vec![Vec::new(); flat.len()];
    for i in 0..flat.len() {
        let free: Vec<usize> = by_item[i].iter().copied().filter(|&f| owner[f].is_none()).collect();
        if free.iter().map(|&f| face_area[f]).sum::<f64>() < MIN_M2 {
            continue;
        }
        for &f in &free {
            owner[f] = Some(i);
        }
        won[i] = free;
    }
    drop(by_item);
    let mut out: Vec<Out> = Vec::new();
    for (i, f) in flat.iter().enumerate() {
        if won[i].is_empty() {
            continue;
        }
        let parts: Vec<Mp> = won[i].iter().map(|&k| Mp::new(vec![faces.0[k].clone()])).collect();
        let u = if parts.len() == 1 { parts.into_iter().next().unwrap() } else { ops::union_all(parts.iter()) };
        // (opened by 1 cm: a piece cut by a neighbour whose edge is a few millimetres off keeps a hairline along it; Python's overlays snap to
        // a 1 cm grid and have none)
        let piece = if (ops::area(&f.geom) - ops::area(&u)).abs() > 1e-9 { ops::wide(&u, HAIRLINE_M) } else { u };
        if ops::area(&piece) < MIN_M2 {
            continue;
        }
        out.push(Out {
            id: format!("g0-{}-{}", f.kind.typ, f.item.r#ref),
            typ: f.kind.typ.clone(),
            name: f.item.name.clone(),
            source: if f.item.r#ref.starts_with("vb") { "vancouver".into() } else { f.kind.source.clone() },
            method: f.kind.method.clone(),
            r#ref: Some(f.item.r#ref.clone()),
            geom: piece,
        });
    }
    let free_faces: Vec<Mp> = faces.0.iter().enumerate().filter(|(k, _)| owner[*k].is_none()).map(|(_, f)| Mp::new(vec![f.clone()])).collect();
    let rest0 = ops::union_all(free_faces.iter());
    drop((flat, faces, free_faces));
    lap.lap("the kinds take the ground");

    // ---- what is left that a path or a road runs through is that path's or that street's ground
    // (opened by 1 cm: pieces that touch leave slits of a millionth of a metre between them, which join the left-over ground and make its
    // outline look 4 times as long. The Python overlays snap to a 1 cm grid, so they have none)
    let rest = ops::wide(&rest0, HAIRLINE_M);
    let line_boxes: Vec<Option<Rect<f64>>> = inp.lines.iter().map(|l| bbox_of(&l.lines)).collect();
    let line_index = Index::new(line_boxes.iter().copied());
    let mut kept: Vec<Polygon<f64>> = Vec::new();
    for p in rest.0.iter().filter(|p| p.unsigned_area() > 0.0) {
        let Some(r) = p.bounding_rect() else { continue };
        let p_index = SegIndex::new(&Mp::new(vec![p.clone()]));
        let mut on: Vec<(f64, usize)> = line_index.query(&r).into_iter().map(|k| (length_in(&p_index, &inp.lines[k].lines), k)).collect();
        on.sort_by(|a, b| b.partial_cmp(a).unwrap());
        if on.first().map_or(true, |x| x.0 <= 1.0) {
            kept.push(p.clone());
            continue;
        }
        let top = &inp.lines[on[0].1];
        let pm = Mp::new(vec![p.clone()]);
        // inside a block a road is a back lane, a driveway, a parking aisle: an alley, not the street
        let in_block = land_within.as_ref().map_or(false, |w| ops::area(&w.clip(&pm)) > 0.5 * p.unsigned_area());
        if top.typ != "road" && !in_block {
            kept.push(p.clone());
            continue;
        }
        let kind = if in_block { if top.typ == "road" { "alley" } else { "yard" } } else { "street" };
        if kind == "alley" {
            // the alley is the road itself, as wide as OSM says (else ALLEY_W_M), not the whole piece
            let bands: Vec<Mp> = on
                .iter()
                .filter(|(l, k)| *l > 1.0 && inp.lines[*k].typ == "road")
                .flat_map(|(_, k)| inp.lines[*k].lines.iter().map(move |ls| ops::buffer_line_flat(ls, inp.lines[*k].width.unwrap_or(ALLEY_W_M) / 2.0)))
                .collect();
            let lane = ops::intersection(&pm, &ops::union_all(bands.iter()));
            for q in &lane.0 {
                if q.unsigned_area() >= MIN_M2 {
                    let qm = Mp::new(vec![q.clone()]);
                    let (cx, cy) = centroid_id(&qm);
                    out.push(Out {
                        id: format!("g0-alley-{}-{}-{}", top.r#ref, cx, cy),
                        typ: "alley".into(),
                        name: top.name.clone(),
                        source: "osm".into(),
                        method: "mapped".into(),
                        r#ref: Some(top.r#ref.clone()),
                        geom: qm,
                    });
                }
            }
            kept.extend(ops::difference(&pm, &lane).0.into_iter().filter(|q| q.unsigned_area() > 0.0));
            continue;
        }
        let (cx, cy) = centroid_id(&pm);
        out.push(Out {
            id: format!("g0-{}-{}-{}-{}", kind, top.r#ref, cx, cy),
            typ: kind.into(),
            name: top.name.clone(),
            source: "osm".into(),
            method: "mapped".into(),
            r#ref: Some(top.r#ref.clone()),
            geom: pm,
        });
    }
    lap.lap("the ground a road or path runs through");

    // ---- a sliver joins the neighbour it shares the most edge with
    let near_index = NearIndex::tagged(out.iter().enumerate().flat_map(|(k, o)| rings(&o.geom).into_iter().map(move |r| (k, r))));
    lap.lap("slivers: the index");
    let mut extra: Vec<(usize, LineString<f64>)> = Vec::new();
    let mut extra_index: Option<NearIndex> = None;
    let mut fresh_index: Option<NearIndex> = None;
    // (the first ring of `extra` that is not in `extra_index`)
    let mut fresh_from = usize::MAX;
    let mut left: Vec<Polygon<f64>> = Vec::new();
    // (the slivers of one item are joined to it in one union at the end: a union with the item's whole outline for each sliver was slow)
    let mut joined: BTreeMap<usize, Vec<Mp>> = BTreeMap::new();
    for p in kept {
        let mut lens: BTreeMap<usize, f64> = near_index.covered_by_tag(std::iter::once(p.exterior()).chain(p.interiors()), NEAR_M);
        for ei in [&extra_index, &fresh_index].into_iter().flatten() {
            for (k, v) in ei.covered_by_tag(std::iter::once(p.exterior()).chain(p.interiors()), NEAR_M) {
                *lens.entry(k).or_insert(0.0) += v;
            }
        }
        let mut near: Vec<(f64, usize)> = lens.into_iter().map(|(k, v)| (v, k)).collect();
        near.sort_by(|a, b| b.partial_cmp(a).unwrap());
        let streets: Vec<&(f64, usize)> = near.iter().filter(|(l, k)| out[*k].typ == "street" && *l > 0.5).collect();
        let row = inp.has_parcels && !streets.is_empty() && land.is_none();
        let mut cand = near.clone();
        if land.is_some() {
            let ns: Vec<(f64, usize)> = near.iter().copied().filter(|(_, k)| out[*k].typ != "street").collect();
            if !ns.is_empty() {
                cand = ns;
            }
        }
        // a building's ground item is its footprint, exactly: a strip beside it joins another neighbour, or stays (a yard)
        cand.retain(|(_, k)| out[*k].typ != "building");
        let a = p.unsigned_area();
        let sliver = a < SLIVER_M2 || 2.0 * a / perimeter(&p) < SLIVER_W_M;
        if (sliver && cand.first().map_or(false, |c| c.0 > 0.1)) || row {
            let k = if row { streets[0].1 } else { cand[0].1 };
            joined.entry(k).or_default().push(Mp::new(vec![p.clone()]));
            let before = extra.len();
            extra.push((k, p.exterior().clone()));
            extra.extend(p.interiors().iter().map(|r| (k, r.clone())));
            // (the rings since the last big index are in a small one: an index of all of them, built again for each sliver, took time as the square of their number)
            fresh_from = fresh_from.min(before);
            if extra.len() - fresh_from > FRESH_RINGS {
                extra_index = Some(NearIndex::tagged(extra.iter().map(|(k, l)| (*k, l))));
                fresh_index = None;
                fresh_from = usize::MAX;
            } else {
                fresh_index = Some(NearIndex::tagged(extra[fresh_from..].iter().map(|(k, l)| (*k, l))));
            }
        } else {
            left.push(p);
        }
    }
    for (k, ps) in joined {
        let mut parts = vec![out[k].geom.clone()];
        parts.extend(ps);
        out[k].geom = ops::union_all(parts.iter());
    }
    lap.lap("slivers");

    // ---- the rest: a yard where it lies in a block, else unknown
    left.sort_by_key(|p| centroid_id(&Mp::new(vec![p.clone()])));
    for p in left {
        let pm = Mp::new(vec![p.clone()]);
        let yard = land_within.as_ref().map_or(false, |w| ops::area(&w.clip(&pm)) > 0.5 * p.unsigned_area());
        let kind = if yard { "yard" } else { "unknown" };
        let (cx, cy) = centroid_id(&pm);
        out.push(Out { id: format!("g0-{kind}-{cx}-{cy}"), typ: kind.into(), name: None, source: "urbanstyle".into(), method: "derived".into(), r#ref: None, geom: pm });
    }
    // (an unknown sliver is a gap below: it joins its neighbour)
    out.retain(|o| o.typ != "unknown");
    lap.lap("yards");

    // ---- the partition made exact: what no item holds joins the neighbour it shares the most edge with
    // (an item in several parts is closed by 1 cm first: pieces a millimetre from the main body, left by the cuts of the earlier kinds, join it)
    for o in out.iter_mut().filter(|o| o.geom.0.len() > 1) {
        o.geom = ops::buffer_mitre(&ops::buffer_mitre(&o.geom, HAIRLINE_M / 2.0), -HAIRLINE_M / 2.0);
    }
    lap.lap("partition: closing the items");
    let all = ops::union_all(out.iter().map(|o| &o.geom));
    lap.lap("partition: the union");
    let gaps = ops::difference(area, &all);
    lap.lap("partition: the gaps");
    let idx = NearIndex::tagged(out.iter().enumerate().flat_map(|(k, o)| rings(&o.geom).into_iter().map(move |r| (k, r))));
    lap.lap("partition: the index");
    let mut add: BTreeMap<usize, Vec<Mp>> = BTreeMap::new();
    for g in gaps.0.iter().filter(|g| g.unsigned_area() > 0.0) {
        let lens = idx.covered_by_tag(std::iter::once(g.exterior()).chain(g.interiors()), NEAR_M);
        if let Some((k, _)) = lens.into_iter().filter(|(_, l)| *l > 0.0).max_by(|a, b| a.1.partial_cmp(&b.1).unwrap()) {
            add.entry(k).or_default().push(Mp::new(vec![g.clone()]));
        }
    }
    lap.lap("partition: gaps to neighbours");
    for (k, gs) in add {
        let mut parts = vec![out[k].geom.clone()];
        parts.extend(gs);
        out[k].geom = ops::union_all(parts.iter());
    }
    lap.lap("the partition");

    // ---- one polygon per row
    let mut rows = Vec::new();
    for o in out {
        let ps: Vec<Polygon<f64>> = o.geom.0.into_iter().filter(|p| p.unsigned_area() >= MIN_ROW_M2).collect();
        let single = ps.len() == 1;
        for (n, p) in ps.into_iter().enumerate() {
            rows.push(Ground {
                id: if single { o.id.clone() } else { format!("{}/{}", o.id, n + 1) },
                typ: o.typ.clone(),
                name: o.name.clone(),
                source: o.source.clone(),
                method: o.method.clone(),
                r#ref: o.r#ref.clone(),
                geom: p,
            });
        }
    }
    rows
}

fn bbox_of(ls: &[LineString<f64>]) -> Option<Rect<f64>> {
    ls.iter().filter_map(|l| l.bounding_rect()).reduce(|a, b| {
        Rect::new(Coord { x: a.min().x.min(b.min().x), y: a.min().y.min(b.min().y) }, Coord { x: a.max().x.max(b.max().x), y: a.max().y.max(b.max().y) })
    })
}

/// The numbers this crate chooses, for the manifest `urban.meta` (`chosen.<name>`): name, value, what it is.
pub fn chosen() -> Vec<(String, f64, String)> {
    vec![
        ("ground.MIN_M2".to_string(), MIN_M2, "A piece of ground smaller than this is left to its neighbours.".to_string()),
        ("ground.SLIVER_M2".to_string(), SLIVER_M2, "Left-over ground smaller than this, or thinner than `SLIVER_W_M` on average (twice its area over its outline), is a sliver.".to_string()),
        ("ground.SLIVER_W_M".to_string(), SLIVER_W_M, "a chosen value".to_string()),
        ("ground.ALLEY_W_M".to_string(), ALLEY_W_M, "An alley's width where OSM gives none (chosen).".to_string()),
        ("ground.NEAR_M".to_string(), NEAR_M, "Two outlines that run within this of each other share an edge.".to_string()),
        ("ground.HAIRLINE_M".to_string(), HAIRLINE_M, "A strip of left-over ground thinner than this is a gap between two pieces that touch, not ground.".to_string()),
    ]
}
