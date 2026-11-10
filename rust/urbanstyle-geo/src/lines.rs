//! Positions along a line: `line.project(pt)` and `line.interpolate(s)` of shapely, in metres (the axes of the spaces, `product._st`).
use geo::{Coord, LineLocatePoint, LineString, Point};

pub fn length(line: &LineString<f64>) -> f64 {
    line.0.windows(2).map(|w| (w[1].x - w[0].x).hypot(w[1].y - w[0].y)).sum()
}

/// The distance along `line` of the point of the line nearest to `p`.
pub fn project(line: &LineString<f64>, p: Coord<f64>) -> f64 {
    line.line_locate_point(&Point::from(p)).unwrap_or(0.0) * length(line)
}

/// The point at distance `s` along `line` (`s` is kept inside the line).
pub fn interpolate(line: &LineString<f64>, s: f64) -> Option<Coord<f64>> {
    let mut left = s.max(0.0);
    for w in line.0.windows(2) {
        let seg = (w[1].x - w[0].x).hypot(w[1].y - w[0].y);
        if left <= seg && seg > 0.0 {
            let t = left / seg;
            return Some(Coord { x: w[0].x + t * (w[1].x - w[0].x), y: w[0].y + t * (w[1].y - w[0].y) });
        }
        left -= seg;
    }
    line.0.last().copied()
}

/// The part of `line` between the distances `s0` and `s1` along it (`shapely.ops.substring`).
pub fn substring(line: &LineString<f64>, s0: f64, s1: f64) -> LineString<f64> {
    let (s0, s1) = (s0.max(0.0), s1.min(length(line)));
    let mut out: Vec<Coord<f64>> = Vec::new();
    if s1 <= s0 {
        return LineString::new(out);
    }
    out.extend(interpolate(line, s0));
    let mut at = 0.0;
    for w in line.0.windows(2) {
        at += (w[1].x - w[0].x).hypot(w[1].y - w[0].y);
        if at > s0 + 1e-9 && at < s1 - 1e-9 {
            out.push(w[1]);
        }
    }
    out.extend(interpolate(line, s1));
    LineString::new(out)
}

/// Lines joined end to end where exactly two of them meet (`shapely.line_merge`, for lines that are already cut at their crossings).
pub fn merge(lines: Vec<LineString<f64>>) -> Vec<LineString<f64>> {
    use std::collections::HashMap;
    let key = |c: &Coord<f64>| (c.x.to_bits(), c.y.to_bits());
    let mut lines: Vec<Option<Vec<Coord<f64>>>> = lines.into_iter().filter(|l| l.0.len() >= 2).map(|l| Some(l.0)).collect();
    loop {
        let mut ends: HashMap<(u64, u64), Vec<usize>> = HashMap::new();
        for (i, l) in lines.iter().enumerate() {
            if let Some(l) = l {
                ends.entry(key(&l[0])).or_default().push(i);
                ends.entry(key(l.last().unwrap())).or_default().push(i);
            }
        }
        // two different lines meet at a point where nothing else ends: join them
        // (the pair with the lowest line numbers first: the order of a hash map changes from run to run, and so did the start of the merged lines)
        let Some(v) = ends.values().filter(|v| v.len() == 2 && v[0] != v[1]).min_by_key(|v| (v[0].min(v[1]), v[0].max(v[1]))).cloned() else { break };
        let (mut a, mut b) = (lines[v[0]].take().unwrap(), lines[v[1]].take().unwrap());
        let (a0, a1, b0, b1) = (key(&a[0]), key(a.last().unwrap()), key(&b[0]), key(b.last().unwrap()));
        if a1 == b0 {
        } else if a1 == b1 {
            b.reverse();
        } else if a0 == b0 {
            a.reverse();
        } else {
            std::mem::swap(&mut a, &mut b); // the start of `a` meets the end of `b`
        }
        a.extend(b.into_iter().skip(1));
        lines[v[0]] = Some(a);
    }
    lines.into_iter().flatten().map(LineString::new).collect()
}

/// `line` moved sideways by `d` (left is positive), vertex by vertex along the mean of the normals of its two segments (`offset_curve`).
pub fn offset(line: &LineString<f64>, d: f64) -> LineString<f64> {
    let p = &line.0;
    let normal = |a: &Coord<f64>, b: &Coord<f64>| {
        let h = (b.x - a.x).hypot(b.y - a.y).max(1e-12);
        (-(b.y - a.y) / h, (b.x - a.x) / h)
    };
    let mut out = Vec::with_capacity(p.len());
    for i in 0..p.len() {
        let n = match (i.checked_sub(1).map(|j| normal(&p[j], &p[i])), p.get(i + 1).map(|q| normal(&p[i], q))) {
            (Some(a), Some(b)) => {
                let (x, y) = (a.0 + b.0, a.1 + b.1);
                let h = x.hypot(y).max(1e-12);
                // the miter: the length that keeps the offset segments at distance d
                let k = 1.0 / ((a.0 * b.0 + a.1 * b.1 + 1.0) / 2.0).sqrt().max(0.2);
                (x / h * k, y / h * k)
            }
            (Some(a), None) => a,
            (None, Some(b)) => b,
            (None, None) => (0.0, 0.0),
        };
        out.push(Coord { x: p[i].x + n.0 * d, y: p[i].y + n.1 * d });
    }
    LineString::new(out)
}

/// The lines as shapely's `line_merge(union_all(lines))` gives them: a segment that two lines both hold is kept once (the union of lines
/// dissolves what overlaps), and what meets end to end is joined.
pub fn dissolve(lines: Vec<LineString<f64>>) -> Vec<LineString<f64>> {
    use std::collections::HashSet;
    let key = |c: &Coord<f64>| (c.x.to_bits(), c.y.to_bits());
    let mut seen: HashSet<((u64, u64), (u64, u64))> = HashSet::new();
    let mut segs: Vec<LineString<f64>> = Vec::new();
    for l in &lines {
        for w in l.0.windows(2) {
            let (a, b) = (key(&w[0]), key(&w[1]));
            if a == b {
                continue;
            }
            if seen.insert(if a < b { (a, b) } else { (b, a) }) {
                segs.push(LineString::new(vec![w[0], w[1]]));
            }
        }
    }
    merge(segs)
}

/// `line` moved sideways by `d` (left is positive), vertex by vertex along the local normal: the same vertices, the same direction
/// (`network.shift_line`; shapely's `offset_curve` turns a line round or empties it for a negative offset).
pub fn shift(line: &LineString<f64>, d: f64) -> LineString<f64> {
    let c = &line.0;
    LineString::new(
        (0..c.len())
            .map(|i| {
                let (a, b) = (c[i.saturating_sub(1)], c[(i + 1).min(c.len() - 1)]);
                let (nx, ny) = (-(b.y - a.y), b.x - a.x);
                let h = nx.hypot(ny);
                let (nx, ny) = if h > 0.0 { (nx / h, ny / h) } else { (0.0, 0.0) };
                Coord { x: c[i].x + nx * d, y: c[i].y + ny * d }
            })
            .collect(),
    )
}
