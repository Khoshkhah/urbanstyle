//! Polygon operations: the Python helpers `union_all`, `D` (difference), `I` (intersection), `buffer`, `wide` of `simready.py` and
//! `sr_blocks.py`, on `MultiPolygon`s in metres.
use geo::algorithm::buffer::{BufferStyle, LineCap, LineJoin};
use geo::algorithm::orient::{Direction, Orient};
use geo::{Area, BooleanOps, Buffer, Contains, Coord, LineString, MultiPolygon, Point, Polygon};
use crate::index::SegIndex;
use geo::{BoundingRect, InteriorPoint};
use std::collections::HashMap;

pub type Mp = MultiPolygon<f64>;

fn key(c: &Coord<f64>) -> (u64, u64) {
    (c.x.to_bits(), c.y.to_bits())
}

/// A ring that touches itself at a vertex, as separate rings (a loop is cut off at the vertex that is visited twice).
fn split_ring(r: &LineString<f64>) -> Vec<LineString<f64>> {
    let mut pts = r.0.clone();
    if pts.len() > 1 && pts.first() == pts.last() {
        pts.pop();
    }
    let (mut stack, mut pos, mut rings): (Vec<Coord<f64>>, HashMap<(u64, u64), usize>, Vec<LineString<f64>>) = (Vec::new(), HashMap::new(), Vec::new());
    let close = |mut v: Vec<Coord<f64>>| {
        v.push(v[0]);
        LineString::new(v)
    };
    for c in pts {
        if let Some(&k) = pos.get(&key(&c)) {
            let lp: Vec<Coord<f64>> = stack.drain(k..).collect();
            for x in &lp {
                pos.remove(&key(x));
            }
            if lp.len() >= 3 {
                rings.push(close(lp));
            }
        }
        pos.insert(key(&c), stack.len());
        stack.push(c);
    }
    if stack.len() >= 3 {
        rings.push(close(stack));
    }
    rings
}

/// The polygons as GEOS gives them: a polygon whose outline touches itself at a vertex is two polygons (`i_overlay` keeps it as one with a
/// pinch). A piece that is cut in two there by an erosion is then two pieces from the start, as in the Python reference.
pub fn normalize(mp: Mp) -> Mp {
    let mut out = Vec::with_capacity(mp.0.len());
    for p in mp.0 {
        let rings = split_ring(p.exterior());
        if rings.len() <= 1 {
            out.push(p);
            continue;
        }
        let mut polys: Vec<(Polygon<f64>, Vec<LineString<f64>>)> = rings.into_iter().map(|r| (Polygon::new(r, vec![]), vec![])).collect();
        for h in p.interiors() {
            if let Some(c) = h.0.first() {
                if let Some(i) = polys.iter().position(|(q, _)| q.contains(&Point::from(*c))) {
                    polys[i].1.push(h.clone());
                }
            }
        }
        out.extend(polys.into_iter().filter(|(q, _)| q.unsigned_area() > 1e-9).map(|(q, hs)| Polygon::new(q.exterior().clone(), hs)));
    }
    // (the split rings can wind the other way: an overlay reads a polygon by its winding, so a hole wound like its outline is lost, and a later
    // union of the result fills it: Monaco's left-over ground came back 2,400 m2 larger)
    MultiPolygon::new(out).orient(Direction::Default)
}

/// Every exterior ring counter-clockwise and every hole clockwise. `i_overlay` reads the polygons of a union by their winding: input of the
/// other winding order is lost in a union (a lane drawn the other way round vanished from the street). Orient the input of an overlay.
pub fn orient(a: &Mp) -> Mp {
    a.orient(Direction::Default)
}

/// shapely's default mitre limit: the longest miter, as a multiple of the buffer distance.
pub const MITRE_LIMIT: f64 = 5.0;

/// `i_overlay` states the limit as the smallest interior angle (radians) that still gets a sharp corner; a smaller angle is cut off. A
/// miter of length `limit * d` belongs to the angle `2 * asin(1 / limit)` (23 degrees for shapely's limit of 5).
fn miter_angle(limit: f64) -> f64 {
    2.0 * (1.0 / limit).asin()
}

pub fn union_all<'a>(parts: impl IntoIterator<Item = &'a Mp>) -> Mp {
    normalize(geo::unary_union(parts))
}

pub fn union(a: &Mp, b: &Mp) -> Mp {
    normalize(a.union(b))
}

pub fn difference(a: &Mp, b: &Mp) -> Mp {
    normalize(a.difference(b))
}

pub fn intersection(a: &Mp, b: &Mp) -> Mp {
    normalize(a.intersection(b))
}

pub fn area(a: &Mp) -> f64 {
    a.unsigned_area()
}

/// `a.buffer(d)` with round joins (shapely's default); a negative `d` shrinks.
pub fn buffer(a: &Mp, d: f64) -> Mp {
    normalize(a.buffer(d))
}

/// `a.buffer(d, join_style="mitre")`.
pub fn buffer_mitre(a: &Mp, d: f64) -> Mp {
    normalize(a.buffer_with_style(BufferStyle::new(d).line_join(LineJoin::Miter(miter_angle(MITRE_LIMIT)))))
}

/// A line buffered by `half` with round caps (shapely's default).
pub fn buffer_line(line: &LineString<f64>, half: f64) -> Mp {
    normalize(line.buffer(half))
}

/// A line buffered by `half` with flat caps (`cap_style="flat"`): a band that ends square at the ends of the line.
pub fn buffer_line_flat(line: &LineString<f64>, half: f64) -> Mp {
    normalize(line.buffer_with_style(BufferStyle::new(half).line_cap(LineCap::Butt)))
}

/// The parts of `a` at least `min_w` wide (`blocks.wide`): the opening `buffer(-w/2, mitre).buffer(w/2, mitre)`, inside `a`.
pub fn wide(a: &Mp, min_w: f64) -> Mp {
    let h = min_w / 2.0;
    let opened = buffer_mitre(&buffer_mitre(a, -h), h);
    intersection(&opened, a)
}

/// The polygons of `a` with an area of at least `min_area`.
pub fn parts_over(a: &Mp, min_area: f64) -> Vec<Polygon<f64>> {
    a.0.iter().filter(|p| p.unsigned_area() >= min_area).cloned().collect()
}

/// `a` cut by `lines` (shapely's `polygonize` of the outline and the lines, inside `a`): the faces of `a` that the lines make. A line that
/// ends inside a face leaves it whole. Built on `i_overlay`'s slice.
pub fn slice(a: &Mp, lines: &[LineString<f64>]) -> Mp {
    use i_overlay::core::fill_rule::FillRule;
    use i_overlay::float::slice::FloatSlice;
    let a = orient(a);
    let shapes: Vec<Vec<Vec<[f64; 2]>>> = a
        .0
        .iter()
        .map(|p| std::iter::once(p.exterior()).chain(p.interiors().iter()).map(|r| r.0.iter().map(|c| [c.x, c.y]).collect()).collect())
        .collect();
    let paths: Vec<Vec<[f64; 2]>> = lines.iter().filter(|l| l.0.len() >= 2).map(|l| l.0.iter().map(|c| [c.x, c.y]).collect()).collect();
    if paths.is_empty() {
        return a;
    }
    let cut: Vec<Vec<Vec<[f64; 2]>>> = shapes.slice_by(&paths, FillRule::NonZero);
    let ring = |r: &Vec<[f64; 2]>| {
        let mut v: Vec<Coord<f64>> = r.iter().map(|p| Coord { x: p[0], y: p[1] }).collect();
        if v.first() != v.last() {
            v.push(v[0]);
        }
        LineString::new(v)
    };
    normalize(MultiPolygon::new(cut.iter().filter(|s| !s.is_empty()).map(|s| Polygon::new(ring(&s[0]), s[1..].iter().map(ring).collect())).collect()))
}

/// Lines buffered by `half` with flat caps and bevelled joins: fewer corners than round ones, for a test of nearness where the shape of
/// the corners does not matter.
pub fn buffer_lines_coarse(lines: &geo::MultiLineString<f64>, half: f64) -> Mp {
    normalize(lines.buffer_with_style(BufferStyle::new(half).line_cap(LineCap::Butt).line_join(LineJoin::Bevel)))
}

/// `g` inside (`inside`) or outside the polygons whose edges are in `idx`, looking only at the edges near `g`: `g` is cut by them
/// (`slice`) and each piece is kept by a point inside it. An overlay with a polygon of 20,000 edges takes the time of all of them for each
/// small `g`: 701 strips against Monaco's blocks took 16 s, 4,000 buildings against its land 25 s.
pub fn clip_by(g: &Mp, idx: &SegIndex, inside: bool) -> Mp {
    let Some(r) = g.bounding_rect() else { return Mp::new(vec![]) };
    let edges = idx.edges_in(&r);
    let wanted = |f: &Polygon<f64>| f.interior_point().map_or(false, |p| idx.contains(p.0) == inside);
    if edges.is_empty() {
        // (no edge near: all of `g` is inside or all of it outside)
        // (oriented: the input may wind the other way, and a later union would lose it)
        return if g.0.first().map_or(false, wanted) { orient(g) } else { Mp::new(vec![]) };
    }
    let faces: Vec<Mp> = slice(g, &edges).0.into_iter().filter(|f| wanted(f)).map(|f| Mp::new(vec![f])).collect();
    union_all(faces.iter())
}

fn snap_ring(r: &LineString<f64>, grid: f64) -> Option<LineString<f64>> {
    let mut v: Vec<Coord<f64>> = Vec::with_capacity(r.0.len());
    for c in &r.0 {
        let p = Coord { x: (c.x / grid).round() * grid, y: (c.y / grid).round() * grid };
        if v.last() != Some(&p) {
            v.push(p);
        }
    }
    if v.first() != v.last() {
        v.push(v[0]);
    }
    (v.len() >= 4).then(|| LineString::new(v))
}

/// The polygons with every corner on a grid of `grid` metres, made valid again (shapely's `make_valid(set_precision(x, grid))`). Parts
/// that are snapped together share their edges exactly: a union of them leaves no slit, and an overlay is not given a hairline.
pub fn snap(a: &Mp, grid: f64) -> Mp {
    let polys: Vec<Polygon<f64>> = a
        .0
        .iter()
        .filter_map(|p| {
            let ext = snap_ring(p.exterior(), grid)?;
            Some(Polygon::new(ext, p.interiors().iter().filter_map(|r| snap_ring(r, grid)).collect()))
        })
        .collect();
    // (a union with nothing: a union of the one multipolygon alone dropped polygons of it)
    normalize(orient(&Mp::new(polys)).union(&Mp::new(vec![])))
}
