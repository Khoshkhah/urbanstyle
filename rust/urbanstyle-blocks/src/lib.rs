//! Blocks from SimReady's street face: the Rust port of `src/urbanstyle/sr_blocks.py` (docs/notes/simready-input.md, "The blocks from
//! SimReady's street face"; docs/notes/rust-browser.md, step 2). The same rules, in metres:
//!
//! * the street is SimReady's face less the strips of the drives, plus SimReady's own roadway (its lanes and junction areas);
//! * the blocks are the area less the street; a piece under `MIN_BLOCK_M2`, or thinner than `MIN_BLOCK_W_M`, is street; a piece cut by
//!   the area's edge is kept from `EDGE_BLOCK_M2`;
//! * the sides of a block: for each street carriageway, its line every `STEP_M`, the nearest block within `SIDE_REACH_M`; one row for each
//!   OSM way, the median of the distances;
//! * the corridors: each pedestrian way that does not run along a street's lanes, a strip of its width inside the street, less the
//!   roadway.
use geo::{Area, BooleanOps, BoundingRect, Closest, ClosestPoint, Euclidean, Length, LineString, MultiLineString, Point, Polygon, Rect};
use std::collections::BTreeMap;
use urbanstyle_geo::index::{Index, SegIndex};
use urbanstyle_geo::lines;
use urbanstyle_geo::ops::{self, Mp};

pub const STEP_M: f64 = 5.0;
pub const SIDE_REACH_M: f64 = 25.0;
pub const DRIVE_BUF_M: f64 = 4.0;
pub const DRIVE_KEEP_M: f64 = 7.0;
pub const EDGE_BLOCK_M2: f64 = 10.0;
pub const MIN_BLOCK_M2: f64 = 400.0;
pub const MIN_BLOCK_W_M: f64 = 8.0;
pub const SIDEWALK_ZONE_M: f64 = 8.0;
/// Features of the land thinner than this (1 cm) are not kept.
pub const HAIRLINE_M: f64 = 0.01;

/// The width of a pedestrian way that OSM gives no width for (`blocks.PATH_W`, chosen).
pub fn path_width(class: &str) -> f64 {
    match class {
        "pedestrian" => 4.0,
        _ => 3.0,
    }
}

#[derive(Clone)]
pub struct Street {
    pub way: i64,
    pub name: Option<String>,
    pub class: String,
    pub line: LineString<f64>,
}

#[derive(Clone)]
pub struct PathWay {
    pub way: i64,
    pub class: String,
    pub name: Option<String>,
    pub geom: MultiLineString<f64>,
    pub width: Option<f64>,
}

#[derive(Clone)]
pub struct Input {
    pub area: Mp,
    /// SimReady's ground face and its roundabouts' faces at level 0, inside the area.
    pub face: Mp,
    /// The streets' lanes, the streets' junction areas and the lanes of the drives: one multipolygon each (they are indexed: a path is
    /// measured against the lanes near it, not against their union).
    pub lanes: Vec<Mp>,
    pub junctions: Vec<Mp>,
    pub drives: Vec<Mp>,
    pub streets: Vec<Street>,
    pub paths: Vec<PathWay>,
}

pub struct Side {
    pub way: i64,
    pub name: Option<String>,
    pub class: String,
    pub distance_m: f64,
}

pub struct Block {
    pub id: String,
    pub polygon: Polygon<f64>,
    pub sides: Vec<Side>,
}

pub struct Corridor {
    pub id: String,
    pub way: i64,
    pub name: Option<String>,
    pub class: String,
    pub width_m: f64,
    pub width_source: &'static str,
    pub width_method: &'static str,
    pub polygon: Mp,
}

pub struct Output {
    pub blocks: Vec<Block>,
    pub corridors: Vec<Corridor>,
    pub street: Mp,
    /// SimReady's roadway that its face leaves out (m2).
    pub outside_m2: f64,
    /// How many points of the street lines were measured (a check on the sampling).
    pub samples: usize,
}

/// The point of `q` nearest to `line` (shapely's `nearest_points(line, q)[1]`): the least distance is at a vertex of one of the two.
fn nearest_on_polygon(line: &LineString<f64>, q: &Polygon<f64>) -> Option<geo::Coord<f64>> {
    let at = |c: Closest<f64>| match c {
        Closest::Intersection(p) | Closest::SinglePoint(p) => Some(p.0),
        Closest::Indeterminate => None,
    };
    let mut best: (f64, Option<geo::Coord<f64>>) = (f64::INFINITY, None);
    for v in &line.0 {
        if let Some(c) = at(q.closest_point(&Point::from(*v))) {
            let d = (c.x - v.x).hypot(c.y - v.y);
            if d < best.0 {
                best = (d, Some(c));
            }
        }
    }
    for w in q.exterior().0.iter().chain(q.interiors().iter().flat_map(|r| r.0.iter())) {
        if let Some(c) = at(line.closest_point(&Point::from(*w))) {
            let d = (c.x - w.x).hypot(c.y - w.y);
            if d < best.0 {
                best = (d, Some(*w));
            }
        }
    }
    best.1
}

fn mls_len(m: &MultiLineString<f64>) -> f64 {
    m.0.iter().map(|l| Euclidean.length(l)).sum()
}

/// The length of `lines` that lies inside `poly`.
fn length_inside(poly: &Mp, lines: &MultiLineString<f64>) -> f64 {
    if poly.0.is_empty() {
        return 0.0;
    }
    mls_len(&poly.clip(lines, false))
}

fn median(v: &mut [f64]) -> f64 {
    v.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let n = v.len();
    if n % 2 == 1 { v[n / 2] } else { (v[n / 2 - 1] + v[n / 2]) / 2.0 }
}

fn round2(x: f64) -> f64 {
    (x * 100.0).round() / 100.0
}

impl Input {
    /// The same input with every polygon oriented (`ops::orient`): the overlays below need it.
    pub fn oriented(&self) -> Input {
        let o = |v: &Vec<Mp>| v.iter().map(ops::orient).collect::<Vec<_>>();
        Input { area: ops::orient(&self.area), face: ops::orient(&self.face), lanes: o(&self.lanes), junctions: o(&self.junctions), drives: o(&self.drives), ..self.clone() }
    }
}

/// The street: SimReady's face less the drives' strips, plus its own roadway. Returns (the street, the roadway, the roadway that the face
/// leaves out).
pub fn street_face(inp: &Input) -> (Mp, Mp, Mp) {
    let inp = &inp.oriented();
    let street_zone = ops::union_all(inp.lanes.iter().chain(inp.junctions.iter()));
    let drives = ops::difference(&ops::buffer(&ops::union_all(inp.drives.iter()), DRIVE_BUF_M), &ops::buffer(&street_zone, DRIVE_KEEP_M));
    let face = ops::difference(&inp.face, &drives);
    let roadway = ops::intersection(&street_zone, &inp.area);
    let outside = ops::difference(&roadway, &face);
    (ops::union_all([&face, &roadway]), roadway, outside)
}

pub fn build(inp: &Input) -> Output {
    let inp = &inp.oriented();
    let mut lap = urbanstyle_geo::Lap::new("blocks");
    // ---- the street: SimReady's face less the drives' strips, plus its own roadway
    let (face, _roadway, outside) = street_face(inp);
    lap.lap("the street (drives out, roadway in)");

    // ---- the blocks: the area less the street; a thin or small piece is street
    let edge_parts: Vec<Mp> = inp.area.0.iter().map(|p| ops::buffer_line(p.exterior(), 0.05)).collect();
    let edge = ops::union_all(edge_parts.iter());
    let land = ops::difference(&inp.area, &face);
    let mut pieces: Vec<Polygon<f64>> = Vec::new();
    for q in &land.0 {
        let rings: Vec<LineString<f64>> = std::iter::once(q.exterior().clone()).chain(q.interiors().iter().cloned()).collect();
        let cut = length_inside(&edge, &MultiLineString::new(rings)) > 1.0; // (cut by the area's edge)
        if cut {
            // (a neck of a centimetre or less is no neck: the Python reference snaps its overlays to a 1 cm grid, so a hairline that joins
            // two pieces of land at the area's edge is gone there, and each is a block of its own)
            let w = ops::wide(&Mp::new(vec![q.clone()]), HAIRLINE_M);
            pieces.extend(w.0.into_iter().filter(|p| p.unsigned_area() >= EDGE_BLOCK_M2));
        } else {
            let w = ops::wide(&Mp::new(vec![q.clone()]), MIN_BLOCK_W_M);
            pieces.extend(w.0.into_iter().filter(|p| p.unsigned_area() >= MIN_BLOCK_M2));
        }
    }
    // (a fixed order, from the centroids: the numbers after a dot and in `b0-e<k>` do not depend on the order of the overlay's output)
    pieces.sort_by_key(|p| {
        let c = geo::Centroid::centroid(p).unwrap_or(Point::new(0.0, 0.0));
        (c.x().round() as i64, c.y().round() as i64)
    });
    let block_mps: Vec<Mp> = pieces.iter().map(|p| Mp::new(vec![p.clone()])).collect();
    let street = ops::difference(&inp.area, &ops::union_all(block_mps.iter()));
    lap.lap("the blocks");

    // ---- the sides: each street carriageway's line every STEP_M, the nearest block within SIDE_REACH_M
    let index = Index::of_multipolygons(&block_mps);
    let mut dists: BTreeMap<(usize, i64), Vec<f64>> = BTreeMap::new(); // (block, way) -> distances
    let mut meta: BTreeMap<i64, (Option<String>, String, LineString<f64>)> = BTreeMap::new();
    let mut n_samples = 0usize;
    // (an index of the edges: a street is clipped, and a sample measured, by the edges near it, not by the whole polygon)
    let area_edges = SegIndex::new(&inp.area);
    let piece_edges: Vec<std::cell::OnceCell<SegIndex>> = (0..pieces.len()).map(|_| std::cell::OnceCell::new()).collect();
    for c in &inp.streets {
        let clipped = area_edges.clip_line(&c.line, true);
        // (the pieces in the direction of the line and in its order, as shapely gives them: the samples start at the start of each piece)
        let mut parts: Vec<(f64, LineString<f64>)> = clipped
            .into_iter()
            .filter(|p| p.0.len() >= 2)
            .map(|mut p| {
                let (a, b) = (lines::project(&c.line, p.0[0]), lines::project(&c.line, *p.0.last().unwrap()));
                if a > b {
                    p.0.reverse();
                }
                (a.min(b), p)
            })
            .collect();
        parts.sort_by(|x, y| x.0.partial_cmp(&y.0).unwrap());
        // (`clip` can give a line in several pieces that meet end to end: one line again, as shapely's `intersection` gives it)
        let mut merged: Vec<LineString<f64>> = Vec::new();
        for (_, part) in parts {
            match merged.last_mut() {
                Some(prev) if prev.0.last().is_some_and(|e| (e.x - part.0[0].x).hypot(e.y - part.0[0].y) < 1e-6) => prev.0.extend(part.0.into_iter().skip(1)),
                _ => merged.push(part),
            }
        }
        for part in merged {
            let len = lines::length(&part);
            if len < 1.0 {
                continue;
            }
            meta.entry(c.way).or_insert_with(|| (c.name.clone(), c.class.clone(), part.clone()));
            let mut ts: Vec<f64> = (0..=(len / STEP_M) as usize).map(|k| k as f64 * STEP_M).collect();
            ts.push(len);
            for t in ts {
                let Some(co) = lines::interpolate(&part, t) else { continue };
                let r = Rect::new((co.x - SIDE_REACH_M, co.y - SIDE_REACH_M), (co.x + SIDE_REACH_M, co.y + SIDE_REACH_M));
                let mut best: Option<(usize, f64)> = None;
                for b in index.query(&r) {
                    let d = piece_edges[b].get_or_init(|| SegIndex::new(&Mp::new(vec![pieces[b].clone()]))).distance(co);
                    if d <= SIDE_REACH_M && best.map_or(true, |(_, bd)| d < bd) {
                        best = Some((b, d));
                    }
                }
                if let Some((b, d)) = best {
                    dists.entry((b, c.way)).or_default().push(d);
                    n_samples += 1;
                }
            }
        }
    }
    lap.lap("the measuring of the sides");
    let mut by_block: BTreeMap<usize, Vec<(i64, f64)>> = BTreeMap::new();
    for ((b, way), mut ds) in dists {
        by_block.entry(b).or_default().push((way, round2(median(&mut ds))));
    }
    let mut used: BTreeMap<String, usize> = BTreeMap::new();
    let mut blocks = Vec::new();
    for (b, q) in pieces.iter().enumerate() {
        let mut ws = by_block.remove(&b).unwrap_or_default();
        ws.sort_by(|a, b| a.partial_cmp(b).unwrap());
        let mut bid = match ws.first() {
            Some(&(way, _)) => {
                // the side of the way that the block lies on: from the point of the block nearest to the way's line
                let line = &meta[&way].2;
                let left = match nearest_on_polygon(line, q) {
                    Some(nq) => {
                        let s = lines::project(line, nq);
                        let a = lines::interpolate(line, (s - 1.0).max(0.0)).unwrap();
                        let bb = lines::interpolate(line, (s + 1.0).min(lines::length(line))).unwrap();
                        (bb.x - a.x) * (nq.y - a.y) - (bb.y - a.y) * (nq.x - a.x) > 0.0
                    }
                    None => false,
                };
                format!("b0-w{way}{}", if left { 'l' } else { 'r' })
            }
            None => format!("b0-e{b}"),
        };
        let n = used.entry(bid.clone()).or_insert(0);
        *n += 1;
        if *n > 1 {
            bid = format!("{bid}.{n}");
        }
        let sides = ws.iter().map(|&(way, d)| Side { way, name: meta[&way].0.clone(), class: meta[&way].1.clone(), distance_m: d }).collect();
        blocks.push(Block { id: bid, polygon: q.clone(), sides });
    }

    lap.lap("the ids");
    // ---- the corridors: each pedestrian way that is no sidewalk: a strip of its width inside the street, less the roadway
    // (each path against the lanes, junction areas and blocks near it: the street, the roadway and the lanes' zone are one big polygon each,
    // and an overlay with it for each of 475 paths took 4 s on a square kilometre)
    let road_parts: Vec<&Mp> = inp.lanes.iter().chain(inp.junctions.iter()).collect();
    let road_index = Index::new(road_parts.iter().map(|m| m.bounding_rect()));
    let lane_index = Index::new(inp.lanes.iter().map(|m| m.bounding_rect()));
    // (the blocks as one index of edges: a strip is cut only by the edges near it. The union of the blocks near a strip, and a difference with it,
    // took 16 s on Monaco: a block can have thousands of edges, and every one of 701 strips went through all of them)
    let block_edges = SegIndex::new(&Mp::new(block_mps.iter().flat_map(|m| m.0.iter().cloned()).collect()));
    let mut corridors = Vec::new();
    let mut seen: BTreeMap<String, usize> = BTreeMap::new();
    let grow = |r: Rect<f64>, d: f64| Rect::new((r.min().x - d, r.min().y - d), (r.max().x + d, r.max().y + d));
    for p in &inp.paths {
        let Some(bb) = p.geom.bounding_rect() else { continue };
        let len = mls_len(&p.geom);
        let near_lanes: Vec<Mp> = lane_index.query(&grow(bb, SIDEWALK_ZONE_M)).into_iter().map(|k| ops::buffer(&inp.lanes[k], SIDEWALK_ZONE_M)).collect();
        if len > 0.0 && !near_lanes.is_empty() && length_inside(&ops::union_all(near_lanes.iter()), &p.geom) > 0.5 * len {
            continue; // (a sidewalk, not a path)
        }
        let (wid, src, meth) = match p.width {
            Some(w) => (w, "osm", "mapped"),
            None => (path_width(&p.class), "urbanstyle", "chosen"),
        };
        let strip = geo::Buffer::buffer(&p.geom, wid / 2.0);
        let Some(sb) = strip.bounding_rect() else { continue };
        let strip = ops::intersection(&strip, &inp.area);
        let in_street = ops::clip_by(&strip, &block_edges, false);
        let near_road: Vec<&Mp> = road_index.query(&sb).into_iter().map(|k| road_parts[k]).collect();
        let q = ops::difference(&in_street, &ops::union_all(near_road.into_iter()));
        if q.0.is_empty() || ops::area(&q) < 0.5 {
            continue;
        }
        let cid = format!("c0-w{}", p.way);
        let n = seen.entry(cid.clone()).or_insert(0);
        *n += 1;
        let id = if *n > 1 { format!("{cid}.{n}") } else { cid };
        corridors.push(Corridor { id, way: p.way, name: p.name.clone(), class: p.class.clone(), width_m: wid, width_source: src, width_method: meth, polygon: q });
    }
    lap.lap("the corridors");
    Output { blocks, corridors, street, outside_m2: ops::area(&outside), samples: n_samples }
}

/// The numbers this crate chooses, for the manifest `urban.meta` (`chosen.<name>`): name, value, what it is.
pub fn chosen() -> Vec<(String, f64, String)> {
    vec![
        ("blocks.STEP_M".to_string(), STEP_M, "a chosen value".to_string()),
        ("blocks.SIDE_REACH_M".to_string(), SIDE_REACH_M, "a chosen value".to_string()),
        ("blocks.DRIVE_BUF_M".to_string(), DRIVE_BUF_M, "a chosen value".to_string()),
        ("blocks.DRIVE_KEEP_M".to_string(), DRIVE_KEEP_M, "a chosen value".to_string()),
        ("blocks.EDGE_BLOCK_M2".to_string(), EDGE_BLOCK_M2, "a chosen value".to_string()),
        ("blocks.MIN_BLOCK_M2".to_string(), MIN_BLOCK_M2, "a chosen value".to_string()),
        ("blocks.MIN_BLOCK_W_M".to_string(), MIN_BLOCK_W_M, "a chosen value".to_string()),
        ("blocks.SIDEWALK_ZONE_M".to_string(), SIDEWALK_ZONE_M, "a chosen value".to_string()),
        ("blocks.HAIRLINE_M".to_string(), HAIRLINE_M, "Features of the land thinner than this (1 cm) are not kept.".to_string()),
    ]
}
