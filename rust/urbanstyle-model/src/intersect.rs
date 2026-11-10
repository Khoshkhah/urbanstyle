//! An intersection's rank 3 (docs/design/spaces.md): one piece per junction node, the ground nearer to that node than to the intersection's
//! other nodes; a roundabout also its centre (the islands inside the ring). The port of `product.cut_intersection`. The cell of a node is
//! the intersection of the half planes between it and each other node (the cell of a Voronoi diagram, with no Voronoi code).
use crate::MIN_PART_M2;
use geo::{Coord, InteriorPoint, LineString, Polygon};
use urbanstyle_geo::index::{NearIndex, SegIndex};
use urbanstyle_geo::lines;
use urbanstyle_geo::ops::{self, Mp};

/// A piece of a node's cell that lies apart joins the piece it shares the longest edge with, when they share at least this.
const NEAR_M: f64 = 0.05;
/// Two nodes this near are one place: one piece, the first.
const SAME_M: f64 = 0.01;
/// A piece smaller than this is a hairline.
const MIN_PIECE_M2: f64 = 0.01;

/// The half plane of the points nearer to `a` than to `b`, as a large rectangle.
fn half_plane(a: Coord<f64>, b: Coord<f64>) -> Mp {
    const L: f64 = 1.0e5;
    let (mx, my) = ((a.x + b.x) / 2.0, (a.y + b.y) / 2.0);
    let (dx, dy) = (b.x - a.x, b.y - a.y);
    let h = dx.hypot(dy);
    let (ux, uy) = (dx / h, dy / h);
    let (vx, vy) = (-uy, ux);
    let c = |sx: f64, sy: f64| Coord { x: mx + vx * L * sx - ux * L * sy, y: my + vy * L * sx - uy * L * sy };
    let ring = LineString::new(vec![c(1.0, 0.0), c(-1.0, 0.0), c(-1.0, 1.0), c(1.0, 1.0), c(1.0, 0.0)]);
    ops::orient(&Mp::new(vec![Polygon::new(ring, vec![])]))
}

/// The pieces of the intersection `geom`: [(the node, or "centre", or none; the piece)]. `rings` are the lines of the roundabout ring.
pub fn cut(geom: &Mp, nodes: &[(i64, Coord<f64>)], rings: &[LineString<f64>], islands: &[&Mp]) -> Vec<(Option<String>, Mp)> {
    let mut centre: Option<Mp> = None;
    if !rings.is_empty() {
        let loops: Vec<Mp> = lines::merge(rings.to_vec())
            .into_iter()
            .filter(|l| l.0.len() >= 4 && l.0.first() == l.0.last())
            .map(|l| ops::orient(&Mp::new(vec![Polygon::new(l, vec![])])))
            .collect();
        let inside = ops::union_all(loops.iter());
        let idx = SegIndex::new(&inside);
        let isl: Vec<&Mp> = islands.iter().copied().filter(|x| !inside.0.is_empty() && x.interior_point().map_or(false, |p| idx.contains(p.0))).collect();
        if !isl.is_empty() {
            let c = ops::intersection(&ops::union_all(isl.into_iter()), geom);
            if ops::area(&c) >= MIN_PART_M2 {
                centre = Some(c);
            }
        }
    }
    let rest = match &centre {
        Some(c) => ops::difference(geom, c),
        None => geom.clone(),
    };
    // (two nodes at one place: one piece, the first)
    let mut pts: Vec<(i64, Coord<f64>)> = Vec::new();
    for &(k, pt) in nodes {
        if !pts.iter().any(|(_, q)| (pt.x - q.x).hypot(pt.y - q.y) < SAME_M) {
            pts.push((k, pt));
        }
    }
    let mut out: Vec<(Option<String>, Mp)> = Vec::new();
    if pts.len() <= 1 {
        out.push((pts.first().map(|p| p.0.to_string()), rest));
    } else {
        let mut cells: Vec<(i64, Mp)> = Vec::new();
        let mut loose: Vec<Polygon<f64>> = Vec::new();
        for (ki, (k, pt)) in pts.iter().enumerate() {
            let mut cell = rest.clone();
            for (j, (_, pj)) in pts.iter().enumerate() {
                if j != ki {
                    cell = ops::intersection(&cell, &half_plane(*pt, *pj));
                }
            }
            let mut got: Vec<Polygon<f64>> = cell.0.into_iter().filter(|q| geo::Area::unsigned_area(q) > MIN_PIECE_M2).collect();
            got.sort_by(|a, b| geo::Area::unsigned_area(b).partial_cmp(&geo::Area::unsigned_area(a)).unwrap());
            if !got.is_empty() {
                let first = got.remove(0);
                cells.push((*k, Mp::new(vec![first])));
                loose.extend(got);
            }
        }
        for q in loose {
            let near = NearIndex::new(q.exterior().lines().map(|l| LineString::new(vec![l.start, l.end])).collect::<Vec<_>>().iter());
            let best = (0..cells.len())
                .map(|i| (i, near.length_within(cells[i].1 .0.iter().flat_map(|p| std::iter::once(p.exterior()).chain(p.interiors())), NEAR_M)))
                .fold(None::<(usize, f64)>, |b, c| match b {
                    Some(x) if x.1 >= c.1 => Some(x),
                    _ => Some(c),
                });
            if let Some((i, _)) = best {
                cells[i].1 = ops::union(&cells[i].1, &Mp::new(vec![q]));
            }
        }
        out = cells.into_iter().map(|(k, g)| (Some(k.to_string()), g)).collect();
    }
    if let Some(c) = centre {
        out.push((Some("centre".to_string()), c));
    }
    out
}
