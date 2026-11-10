//! An index of boxes (shapely's `STRtree`): which items have a box that meets a given box. The caller then tests the items.
use geo::{BoundingRect, Rect};
use rstar::primitives::{GeomWithData, Rectangle};
use rstar::{RTree, AABB};

pub struct Index {
    tree: RTree<GeomWithData<Rectangle<[f64; 2]>, usize>>,
}

fn rect(r: &Rect<f64>) -> Rectangle<[f64; 2]> {
    Rectangle::from_corners([r.min().x, r.min().y], [r.max().x, r.max().y])
}

impl Index {
    /// The item `i` of the iterator is the answer `i`. An item with no box (an empty geometry) is never an answer.
    pub fn new(rects: impl IntoIterator<Item = Option<Rect<f64>>>) -> Self {
        let items: Vec<_> = rects.into_iter().enumerate().filter_map(|(i, r)| r.map(|r| GeomWithData::new(rect(&r), i))).collect();
        Index { tree: RTree::bulk_load(items) }
    }

    pub fn of_multipolygons(items: &[geo::MultiPolygon<f64>]) -> Self {
        Self::new(items.iter().map(|m| m.bounding_rect()))
    }

    /// The items whose box meets `r`, in no order.
    pub fn query(&self, r: &Rect<f64>) -> Vec<usize> {
        let env = AABB::from_corners([r.min().x, r.min().y], [r.max().x, r.max().y]);
        self.tree.locate_in_envelope_intersecting(&env).map(|g| g.data).collect()
    }
}

/// The edges of a multipolygon in an index, to clip a straight line to it without looking at all the edges (shapely's
/// `polygon.intersection(line)`, which takes the time of the whole polygon: a street that is one polygon of 30,000 edges costs 2 ms a cut).
pub struct SegIndex {
    segs: Vec<(geo::Coord<f64>, geo::Coord<f64>)>,
    tree: RTree<GeomWithData<Rectangle<[f64; 2]>, usize>>,
}

impl SegIndex {
    pub fn new(m: &geo::MultiPolygon<f64>) -> Self {
        let mut segs = Vec::new();
        for p in &m.0 {
            for ring in std::iter::once(p.exterior()).chain(p.interiors()) {
                segs.extend(ring.lines().map(|l| (l.start, l.end)));
            }
        }
        let items: Vec<_> = segs
            .iter()
            .enumerate()
            .map(|(i, (a, b))| GeomWithData::new(Rectangle::from_corners([a.x.min(b.x), a.y.min(b.y)], [a.x.max(b.x), a.y.max(b.y)]), i))
            .collect();
        SegIndex { segs, tree: RTree::bulk_load(items) }
    }

    /// The distance from the point to the polygons: 0 inside, else to the nearest edge.
    pub fn distance(&self, p: geo::Coord<f64>) -> f64 {
        if self.contains(p) {
            return 0.0;
        }
        let mut best = f64::INFINITY;
        for (g, d2) in self.tree.nearest_neighbor_iter_with_distance_2(&[p.x, p.y]) {
            if d2 >= best * best {
                break; // (d2 is the distance to the box of the edge: the edge is at least that far)
            }
            let (a, c) = self.segs[g.data];
            let (dx, dy) = (c.x - a.x, c.y - a.y);
            let l2 = dx * dx + dy * dy;
            let t = if l2 > 0.0 { (((p.x - a.x) * dx + (p.y - a.y) * dy) / l2).clamp(0.0, 1.0) } else { 0.0 };
            best = best.min((p.x - a.x - t * dx).hypot(p.y - a.y - t * dy));
        }
        best
    }

    /// The edges whose box meets `r`, each as a line of two points.
    pub fn edges_in(&self, r: &Rect<f64>) -> Vec<geo::LineString<f64>> {
        let env = AABB::from_corners([r.min().x, r.min().y], [r.max().x, r.max().y]);
        self.tree.locate_in_envelope_intersecting(&env).map(|g| geo::LineString::new(vec![self.segs[g.data].0, self.segs[g.data].1])).collect()
    }

    /// Is the point inside (even-odd rule, a ray to the right)?
    pub fn contains(&self, p: geo::Coord<f64>) -> bool {
        let env = AABB::from_corners([p.x, p.y], [f64::MAX, p.y]);
        let mut inside = false;
        for g in self.tree.locate_in_envelope_intersecting(&env) {
            let (a, b) = self.segs[g.data];
            if (a.y > p.y) != (b.y > p.y) && p.x < a.x + (p.y - a.y) / (b.y - a.y) * (b.x - a.x) {
                inside = !inside;
            }
        }
        inside
    }

    /// The pieces of the segment `a`-`b` that lie inside, each a line of two points. Touching an edge does not split a piece.
    pub fn clip(&self, a: geo::Coord<f64>, b: geo::Coord<f64>) -> Vec<geo::LineString<f64>> {
        self.clip_by(a, b, true)
    }

    /// The pieces of the segment `a`-`b` that lie outside.
    pub fn clip_outside(&self, a: geo::Coord<f64>, b: geo::Coord<f64>) -> Vec<geo::LineString<f64>> {
        self.clip_by(a, b, false)
    }

    /// Where the segment `a`-`b` crosses an edge: the parameters `t` in 0..1, sorted.
    fn crossings(&self, a: geo::Coord<f64>, b: geo::Coord<f64>) -> Vec<f64> {
        let (dx, dy) = (b.x - a.x, b.y - a.y);
        let env = AABB::from_corners([a.x.min(b.x), a.y.min(b.y)], [a.x.max(b.x), a.y.max(b.y)]);
        let mut ts = Vec::new();
        for g in self.tree.locate_in_envelope_intersecting(&env) {
            let (c, d) = self.segs[g.data];
            let (ex, ey) = (d.x - c.x, d.y - c.y);
            let den = dx * ey - dy * ex;
            if den.abs() < 1e-12 {
                continue;
            }
            let t = ((c.x - a.x) * ey - (c.y - a.y) * ex) / den;
            let u = ((c.x - a.x) * dy - (c.y - a.y) * dx) / den;
            if t > 0.0 && t < 1.0 && (0.0..=1.0).contains(&u) {
                ts.push(t);
            }
        }
        ts.sort_by(|x, y| x.partial_cmp(y).unwrap());
        ts
    }

    /// The pieces of a ring or a line that lie inside (`inside`) or outside the polygon. One ray decides where the line starts. After
    /// that the state holds along a segment that crosses no edge, and a ray decides it again after each segment that does.
    pub fn clip_line(&self, line: &geo::LineString<f64>, inside: bool) -> Vec<geo::LineString<f64>> {
        let mut out: Vec<Vec<geo::Coord<f64>>> = Vec::new();
        let Some(&first) = line.0.first() else { return vec![] };
        let mut state = self.contains(first);
        for w in line.0.windows(2) {
            let (a, b) = (w[0], w[1]);
            let (dx, dy) = (b.x - a.x, b.y - a.y);
            let at = |t: f64| geo::Coord { x: a.x + dx * t, y: a.y + dy * t };
            let ts = self.crossings(a, b);
            let mut cuts = vec![0.0];
            cuts.extend(ts.iter().copied());
            cuts.push(1.0);
            for k in 0..cuts.len() - 1 {
                let (s, e) = (cuts[k], cuts[k + 1]);
                if e - s < 1e-12 {
                    continue;
                }
                let here = if ts.is_empty() { state } else { self.contains(at((s + e) / 2.0)) };
                if here != inside {
                    continue;
                }
                match out.last_mut() {
                    Some(l) if (l.last().unwrap().x - at(s).x).abs() < 1e-9 && (l.last().unwrap().y - at(s).y).abs() < 1e-9 => l.push(at(e)),
                    _ => out.push(vec![at(s), at(e)]),
                }
            }
            if !ts.is_empty() {
                state = self.contains(b);
            }
        }
        out.into_iter().map(geo::LineString::new).collect()
    }

    fn clip_by(&self, a: geo::Coord<f64>, b: geo::Coord<f64>, inside: bool) -> Vec<geo::LineString<f64>> {
        self.clip_line(&geo::LineString::new(vec![a, b]), inside)
    }
}

/// Line segments in an index, to measure how much of a ring lies within `r` of them. The same number as `ring ∩ lines.buffer(r)` (round
/// caps and joins), without building the buffer: the part of one segment inside the capsule of another is one interval.
pub struct NearIndex {
    segs: Vec<(geo::Coord<f64>, geo::Coord<f64>)>,
    tags: Vec<usize>,
    tree: RTree<GeomWithData<Rectangle<[f64; 2]>, usize>>,
}

/// The `t` in 0..1 where the segment `a`-`b` lies within `r` of the segment `c`-`d`, as one interval, or none.
fn within(a: geo::Coord<f64>, b: geo::Coord<f64>, c: geo::Coord<f64>, d: geo::Coord<f64>, r: f64) -> Option<(f64, f64)> {
    let (ex, ey) = (d.x - c.x, d.y - c.y);
    let l = ex.hypot(ey);
    let (ux, uy) = if l > 1e-12 { (ex / l, ey / l) } else { (1.0, 0.0) };
    // in the frame of `c`-`d`: x along it, y across it
    let f = |p: geo::Coord<f64>| ((p.x - c.x) * ux + (p.y - c.y) * uy, -(p.x - c.x) * uy + (p.y - c.y) * ux);
    let ((ax, ay), (bx, by)) = (f(a), f(b));
    let (dx, dy) = (bx - ax, by - ay);
    let mut lo = f64::INFINITY;
    let mut hi = f64::NEG_INFINITY;
    let mut add = |s: f64, e: f64| {
        let (s, e) = (s.max(0.0), e.min(1.0));
        if s <= e {
            lo = lo.min(s);
            hi = hi.max(e);
        }
    };
    // the band: 0 <= x <= l and |y| <= r
    let (mut s, mut e) = (0.0f64, 1.0f64);
    let mut ok = true;
    for (p0, dp, min, max) in [(ax, dx, 0.0, l), (ay, dy, -r, r)] {
        if dp.abs() < 1e-12 {
            ok &= p0 >= min && p0 <= max;
        } else {
            let (t0, t1) = ((min - p0) / dp, (max - p0) / dp);
            s = s.max(t0.min(t1));
            e = e.min(t0.max(t1));
        }
    }
    if ok {
        add(s, e);
    }
    // the two discs
    for cx in [0.0, l] {
        let (px, py) = (ax - cx, ay);
        let (qa, qb, qc) = (dx * dx + dy * dy, 2.0 * (px * dx + py * dy), px * px + py * py - r * r);
        if qa < 1e-18 {
            if qc <= 0.0 {
                add(0.0, 1.0);
            }
            continue;
        }
        let disc = qb * qb - 4.0 * qa * qc;
        if disc >= 0.0 {
            let sq = disc.sqrt();
            add((-qb - sq) / (2.0 * qa), (-qb + sq) / (2.0 * qa));
        }
    }
    (lo <= hi).then_some((lo, hi))
}

/// The segment `a`-`b` as pieces of at most `CHUNK_M`. A long edge has a box that meets the box of most queries; its pieces have small ones.
const CHUNK_M: f64 = 10.0;

fn chunks(a: geo::Coord<f64>, b: geo::Coord<f64>) -> impl Iterator<Item = (geo::Coord<f64>, geo::Coord<f64>)> {
    let n = ((b.x - a.x).hypot(b.y - a.y) / CHUNK_M).ceil().max(1.0) as usize;
    let at = move |k: usize| if k == n { b } else { geo::Coord { x: a.x + (b.x - a.x) * k as f64 / n as f64, y: a.y + (b.y - a.y) * k as f64 / n as f64 } };
    (0..n).map(move |k| (at(k), at(k + 1)))
}

impl NearIndex {
    pub fn new<'a>(lines: impl IntoIterator<Item = &'a geo::LineString<f64>>) -> Self {
        Self::tagged(lines.into_iter().map(|l| (0, l)))
    }

    /// Each line has a tag (an owner, say); `covered_by_tag` adds up the length of the segments by tag.
    pub fn tagged<'a>(lines: impl IntoIterator<Item = (usize, &'a geo::LineString<f64>)>) -> Self {
        let (mut segs, mut tags) = (Vec::new(), Vec::new());
        for (t, l) in lines {
            for s in l.lines() {
                for c in chunks(s.start, s.end) {
                    segs.push(c);
                    tags.push(t);
                }
            }
        }
        let items: Vec<_> = segs
            .iter()
            .enumerate()
            .map(|(i, (a, b))| GeomWithData::new(Rectangle::from_corners([a.x.min(b.x), a.y.min(b.y)], [a.x.max(b.x), a.y.max(b.y)]), i))
            .collect();
        NearIndex { segs, tags, tree: RTree::bulk_load(items) }
    }

    /// The length of the lines `rings` that lies within `r` of the indexed segments.
    pub fn length_within<'a>(&self, rings: impl IntoIterator<Item = &'a geo::LineString<f64>>, r: f64) -> f64 {
        let mut total = 0.0;
        for ring in rings {
            for (a, b) in ring.lines().flat_map(|s| chunks(s.start, s.end)) {
                let env = AABB::from_corners([a.x.min(b.x) - r, a.y.min(b.y) - r], [a.x.max(b.x) + r, a.y.max(b.y) + r]);
                let mut iv: Vec<(f64, f64)> =
                    self.tree.locate_in_envelope_intersecting(&env).filter_map(|g| within(a, b, self.segs[g.data].0, self.segs[g.data].1, r)).collect();
                if iv.is_empty() {
                    continue;
                }
                iv.sort_by(|x, y| x.0.partial_cmp(&y.0).unwrap());
                let (mut cur_lo, mut cur_hi) = iv[0];
                let mut covered = 0.0;
                for &(lo, hi) in &iv[1..] {
                    if lo > cur_hi {
                        covered += cur_hi - cur_lo;
                        (cur_lo, cur_hi) = (lo, hi);
                    } else {
                        cur_hi = cur_hi.max(hi);
                    }
                }
                covered += cur_hi - cur_lo;
                total += covered * (b.x - a.x).hypot(b.y - a.y);
            }
        }
        total
    }

    /// The length of the indexed segments that lies within `r` of the lines `rings`, added up by tag.
    pub fn covered_by_tag<'a>(&self, rings: impl IntoIterator<Item = &'a geo::LineString<f64>>, r: f64) -> std::collections::BTreeMap<usize, f64> {
        // (ordered: a sum of floats in the order of a hash map changed in the last digits from run to run)
        let mut by_seg: std::collections::BTreeMap<usize, Vec<(f64, f64)>> = std::collections::BTreeMap::new();
        for ring in rings {
            for (qa, qb) in ring.lines().flat_map(|s| chunks(s.start, s.end)) {
                let env = AABB::from_corners([qa.x.min(qb.x) - r, qa.y.min(qb.y) - r], [qa.x.max(qb.x) + r, qa.y.max(qb.y) + r]);
                for g in self.tree.locate_in_envelope_intersecting(&env) {
                    let (c, d) = self.segs[g.data];
                    if let Some(iv) = within(c, d, qa, qb, r) {
                        by_seg.entry(g.data).or_default().push(iv);
                    }
                }
            }
        }
        let mut out = std::collections::BTreeMap::new();
        for (i, mut iv) in by_seg {
            iv.sort_by(|x, y| x.0.partial_cmp(&y.0).unwrap());
            let (mut cur_lo, mut cur_hi) = iv[0];
            let mut covered = 0.0;
            for &(lo, hi) in &iv[1..] {
                if lo > cur_hi {
                    covered += cur_hi - cur_lo;
                    (cur_lo, cur_hi) = (lo, hi);
                } else {
                    cur_hi = cur_hi.max(hi);
                }
            }
            covered += cur_hi - cur_lo;
            let (c, d) = self.segs[i];
            *out.entry(self.tags[i]).or_insert(0.0) += covered * (d.x - c.x).hypot(d.y - c.y);
        }
        out
    }

    /// The pieces of the lines `rings` that lie within `r` of the indexed segments, each a line of two points (a segment, or a part of one).
    pub fn pieces_within<'a>(&self, rings: impl IntoIterator<Item = &'a geo::LineString<f64>>, r: f64) -> Vec<geo::LineString<f64>> {
        let mut out = Vec::new();
        for ring in rings {
            for s in ring.lines() {
                let (a, b) = (s.start, s.end);
                let env = AABB::from_corners([a.x.min(b.x) - r, a.y.min(b.y) - r], [a.x.max(b.x) + r, a.y.max(b.y) + r]);
                let mut iv: Vec<(f64, f64)> = self.tree.locate_in_envelope_intersecting(&env).filter_map(|g| within(a, b, self.segs[g.data].0, self.segs[g.data].1, r)).collect();
                if iv.is_empty() {
                    continue;
                }
                iv.sort_by(|x, y| x.0.partial_cmp(&y.0).unwrap());
                let at = |t: f64| geo::Coord { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t };
                let (mut lo, mut hi) = iv[0];
                for &(l, h) in &iv[1..] {
                    if l > hi {
                        out.push(geo::LineString::new(vec![at(lo), at(hi)]));
                        (lo, hi) = (l, h);
                    } else {
                        hi = hi.max(h);
                    }
                }
                out.push(geo::LineString::new(vec![at(lo), at(hi)]));
            }
        }
        out.retain(|l| l.0[0] != l.0[1]);
        out
    }

    /// The tag of the indexed segment nearest to any of the points (the distance from a polygon to a line, from its outline's points).
    pub fn nearest_tag(&self, points: impl IntoIterator<Item = geo::Coord<f64>>) -> Option<usize> {
        let mut best: Option<(f64, usize)> = None;
        for p in points {
            for (g, d2) in self.tree.nearest_neighbor_iter_with_distance_2(&[p.x, p.y]) {
                // (d2 is the distance to the box of the segment: the segment is at least that far)
                if best.map_or(false, |(b, _)| d2 >= b * b) {
                    break;
                }
                let (a, c) = self.segs[g.data];
                let (dx, dy) = (c.x - a.x, c.y - a.y);
                let l2 = dx * dx + dy * dy;
                let t = if l2 > 0.0 { (((p.x - a.x) * dx + (p.y - a.y) * dy) / l2).clamp(0.0, 1.0) } else { 0.0 };
                let d = (p.x - a.x - t * dx).hypot(p.y - a.y - t * dy);
                if best.map_or(true, |(b, _)| d < b) {
                    best = Some((d, self.tags[g.data]));
                }
            }
        }
        best.map(|(_, t)| t)
    }
}
