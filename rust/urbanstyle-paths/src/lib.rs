//! The paths at ranks 2 and 3 (docs/design/stretches.md, "The paths"): each path item of the ground (the kind `path`) is cut at its path
//! junction nodes into path sections and path intersections. The port of `paths.assemble` of urbanstyle's Python code; the inputs are
//! read elsewhere (`paths.gather`).
//!
//! - a junction is a node inside a path item where three or more path ends meet (a path that runs through a node counts two); a node
//!   where a path meets a sidewalk or a road is none: there the path ends at the street's edge
//! - the cut: each path line that leaves a junction is cut square at `r` from the node (`r` half the widest path there), across its own
//!   corridor only
//! - a piece under `MIN_PIECE_M2` joins the piece it shares the longest edge with
//! - the face that holds a junction node is that node's path intersection `q<level>-<node>`; every other face is a path section named by
//!   the way with the most length in it, `p<level>-<way>` (a second face of one way `.2`)
use geo::{Area, BoundingRect, Coord, Distance, Euclidean, LineString, Point, Rect};
use std::collections::{BTreeMap, HashMap};
use urbanstyle_geo::index::{Index, NearIndex, SegIndex};
use urbanstyle_geo::lines;
use urbanstyle_geo::ops::{self, Mp};

/// A cut line is drawn this far to each side, then only its piece through the cut point inside the path item is kept.
pub const CUT_HALF_M: f64 = 30.0;
/// A piece of a path item smaller than this joins its neighbour (chosen).
pub const MIN_PIECE_M2: f64 = 2.0;
/// A face smaller than this is a hairline of the noding.
pub const MIN_FACE_M2: f64 = 0.01;
/// Two faces are neighbours when their outlines meet along at least this length.
pub const TOUCH_M: f64 = 0.5;
const NEAR_M: f64 = 0.05;

pub struct PathItem {
    pub id: String,
    pub r#ref: String,
    pub geom: Mp,
}

pub struct Corridor {
    pub name: Option<String>,
    pub width: Option<f64>,
    pub source: Option<String>,
    pub method: Option<String>,
}

pub struct PathLine {
    pub way: String,
    pub class: Option<String>,
    pub name: Option<String>,
    pub src: Option<i64>,
    pub dst: Option<i64>,
    pub line: LineString<f64>,
}

pub struct Input {
    pub level: i32,
    /// A footway's width where OSM gives none (chosen).
    pub footway_w: f64,
    pub items: Vec<PathItem>,
    pub corridors: HashMap<String, Corridor>,
    pub lines: Vec<PathLine>,
}

#[derive(Clone, Debug, PartialEq)]
pub enum Kind {
    Section,
    Intersection,
}

pub struct PathSpace {
    pub id: String,
    pub kind: Kind,
    pub ground: String,
    pub name: Option<String>,
    pub class: Option<String>,
    pub ways: Vec<String>,
    pub nodes: Vec<i64>,
    pub width_m: f64,
    pub width_source: Option<String>,
    pub width_method: Option<String>,
    pub length: Option<f64>,
    pub axis: Option<LineString<f64>>,
    pub geom: Mp,
    pub links: Vec<String>,
}

fn rings(m: &Mp) -> Vec<&LineString<f64>> {
    m.0.iter().flat_map(|p| std::iter::once(p.exterior()).chain(p.interiors())).collect()
}

fn grow(r: Rect<f64>, d: f64) -> Rect<f64> {
    Rect::new(Coord { x: r.min().x - d, y: r.min().y - d }, Coord { x: r.max().x + d, y: r.max().y + d })
}

fn point_rect(c: Coord<f64>) -> Rect<f64> {
    Rect::new(c, c)
}

fn dist(m: &Mp, c: Coord<f64>) -> f64 {
    Euclidean.distance(m, &Point::from(c))
}

fn round2(x: f64) -> f64 {
    (x * 100.0).round() / 100.0
}

pub fn build(inp: &Input) -> Vec<PathSpace> {
    let mut lap = urbanstyle_geo::Lap::new("paths");
    let level = inp.level;
    let all = ops::union_all(inp.items.iter().map(|i| &i.geom));
    let all_idx = SegIndex::new(&all);
    // the path lines that lie in the paths' ground over half their length
    let lines_in: Vec<&PathLine> = inp
        .lines
        .iter()
        .filter(|l| {
            let len = lines::length(&l.line);
            len > 0.0 && all_idx.clip_line(&l.line, true).iter().map(lines::length).sum::<f64>() > 0.5 * len
        })
        .collect();
    // the junction nodes: three or more path ends at one node
    let mut ends: BTreeMap<i64, (Coord<f64>, Vec<usize>)> = BTreeMap::new();
    for (k, l) in lines_in.iter().enumerate() {
        for (node, pt) in [(l.src, l.line.0[0]), (l.dst, *l.line.0.last().unwrap())] {
            if let Some(n) = node {
                ends.entry(n).or_insert((pt, vec![])).1.push(k);
            }
        }
    }
    let item_w: Vec<f64> = inp.items.iter().map(|i| inp.corridors.get(&i.r#ref).and_then(|c| c.width).filter(|w| *w != 0.0).unwrap_or(inp.footway_w)).collect();
    let inner_idx = SegIndex::new(&ops::buffer(&all, -0.25)); // (a node on a path item's edge, where a path meets the street, is no path junction)
    let junctions: Vec<(i64, Coord<f64>)> = ends.iter().filter(|(_, (pt, ls))| ls.len() >= 3 && inner_idx.contains(*pt)).map(|(n, (pt, _))| (*n, *pt)).collect();
    let item_index = Index::new(inp.items.iter().map(|i| i.geom.bounding_rect()));
    let jn_index = Index::new(junctions.iter().map(|(_, p)| Some(point_rect(*p))));
    lap.lap("the junctions");

    // the cuts: square across each path line at r from its junction
    let mut cuts: Vec<(Coord<f64>, LineString<f64>)> = Vec::new();
    for (n, pt) in &junctions {
        let near: Vec<f64> = item_index.query(&grow(point_rect(*pt), 1.0)).into_iter().filter(|&k| dist(&inp.items[k].geom, *pt) < 1.0).map(|k| item_w[k]).collect();
        let r = near.into_iter().fold(f64::NEG_INFINITY, f64::max);
        let r = if r.is_finite() { r } else { inp.footway_w } / 2.0;
        for &li in &ends[n].1 {
            let ln = &lines_in[li].line;
            let len = lines::length(ln);
            let d = |a: Coord<f64>| (a.x - pt.x).hypot(a.y - pt.y);
            let at_start = d(ln.0[0]) < d(*ln.0.last().unwrap());
            if len <= r {
                continue;
            }
            let at = if at_start { r } else { len - r };
            let (Some(p0), Some(p1), Some(c)) = (lines::interpolate(ln, (at - 0.5).max(0.0)), lines::interpolate(ln, (at + 0.5).min(len)), lines::interpolate(ln, at)) else { continue };
            let (dx, dy) = (p1.x - p0.x, p1.y - p0.y);
            let h = dx.hypot(dy);
            let h = if h == 0.0 { 1.0 } else { h };
            let (nx, ny) = (-dy / h * CUT_HALF_M, dx / h * CUT_HALF_M);
            cuts.push((c, LineString::new(vec![Coord { x: c.x - nx, y: c.y - ny }, Coord { x: c.x + nx, y: c.y + ny }])));
        }
    }
    let cut_index = Index::new(cuts.iter().map(|(c, _)| Some(point_rect(*c))));
    lap.lap("the cuts");

    // the faces of each path item
    let mut faces_of: Vec<Vec<Mp>> = Vec::new();
    for it in &inp.items {
        let gm = &it.geom;
        let mut mine: Vec<LineString<f64>> = Vec::new();
        if let Some(r) = gm.bounding_rect() {
            let near_cuts: Vec<usize> = cut_index.query(&grow(r, NEAR_M)).into_iter().filter(|&k| dist(gm, cuts[k].0) <= NEAR_M).collect();
            if !near_cuts.is_empty() {
                // only the piece of the cut through its own point, inside this item (across its own corridor)
                let gmb_idx = SegIndex::new(&ops::buffer(gm, 0.01));
                for k in near_cuts {
                    let (c, ln) = &cuts[k];
                    mine.extend(gmb_idx.clip_line(ln, true).into_iter().filter(|q| Euclidean.distance(q, &Point::from(*c)) < NEAR_M));
                }
            }
        }
        let mut faces: Vec<Mp> = vec![gm.clone()];
        if !mine.is_empty() {
            let cut: Vec<Mp> = ops::slice(gm, &mine).0.into_iter().filter(|p| p.unsigned_area() > MIN_FACE_M2).map(|p| Mp::new(vec![p])).collect();
            if !cut.is_empty() {
                faces = cut;
            }
            // a piece under MIN_PIECE_M2 joins the piece it shares the longest edge with
            while faces.len() > 1 {
                let small = (0..faces.len()).min_by(|&a, &b| ops::area(&faces[a]).partial_cmp(&ops::area(&faces[b])).unwrap()).unwrap();
                if ops::area(&faces[small]) >= MIN_PIECE_M2 {
                    break;
                }
                let f0 = faces.remove(small);
                let near = NearIndex::new(rings(&f0));
                let k = (0..faces.len())
                    .map(|k| (k, near.length_within(rings(&faces[k]), NEAR_M)))
                    .fold((0, f64::NEG_INFINITY), |b, x| if x.1 > b.1 { x } else { b })
                    .0;
                faces[k] = ops::union(&faces[k], &f0);
            }
        }
        faces_of.push(faces);
    }
    lap.lap("the faces");

    // the path spaces
    let line_index = Index::new(lines_in.iter().map(|l| l.line.bounding_rect()));
    struct Rec {
        sp: PathSpace,
    }
    let mut recs: Vec<Rec> = Vec::new();
    let mut count: HashMap<String, usize> = HashMap::new();
    for (ii, it) in inp.items.iter().enumerate() {
        let corr = inp.corridors.get(&it.r#ref);
        let (name, wd, ws, wm) = match corr.and_then(|c| c.width.map(|w| (c, w))) {
            Some((c, w)) => (c.name.clone(), w, c.source.clone(), c.method.clone()),
            None => (corr.and_then(|c| c.name.clone()), item_w[ii], Some("urbanstyle".to_string()), Some("chosen".to_string())),
        };
        for f in &faces_of[ii] {
            let Some(fr) = f.bounding_rect() else { continue };
            let jn: Vec<i64> = jn_index.query(&grow(fr, NEAR_M)).into_iter().filter(|&k| dist(f, junctions[k].1) <= NEAR_M).map(|k| junctions[k].0).collect();
            let f_idx = SegIndex::new(f);
            let mut inside: Vec<(f64, usize, Vec<LineString<f64>>)> = line_index
                .query(&fr)
                .into_iter()
                .map(|k| {
                    let pieces = f_idx.clip_line(&lines_in[k].line, true);
                    (pieces.iter().map(lines::length).sum::<f64>(), k, pieces)
                })
                .filter(|x| x.0 > 0.0)
                .collect();
            inside.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap().then(a.1.cmp(&b.1)));
            let (base, kind) = if let Some(m) = jn.iter().min() {
                (format!("q{level}-{m}"), Kind::Intersection)
            } else if let Some(x) = inside.first() {
                (format!("p{level}-{}", lines_in[x.1].way), Kind::Section)
            } else {
                (format!("p{level}-{}", it.r#ref), Kind::Section)
            };
            let n = count.entry(base.clone()).or_insert(0);
            *n += 1;
            let id = if *n > 1 { format!("{base}.{n}") } else { base };
            let class = inside.first().and_then(|x| lines_in[x.1].class.clone());
            let (mut axis, mut length) = (None, None);
            if kind == Kind::Section {
                if let Some(x) = inside.first() {
                    if let Some(best) = x.2.iter().max_by(|a, b| lines::length(a).partial_cmp(&lines::length(b)).unwrap()) {
                        length = Some(round2(lines::length(best)));
                        axis = Some(best.clone());
                    }
                }
            }
            let mut ways: Vec<String> = Vec::new();
            for x in &inside {
                if !ways.contains(&lines_in[x.1].way) {
                    ways.push(lines_in[x.1].way.clone());
                }
            }
            let mut nodes: Vec<i64> = if !jn.is_empty() {
                jn
            } else {
                let reach = 2.0 * wd.max(1.0);
                jn_index.query(&grow(fr, reach)).into_iter().filter(|&k| dist(f, junctions[k].1) < reach).map(|k| junctions[k].0).collect()
            };
            nodes.sort();
            recs.push(Rec {
                sp: PathSpace {
                    id,
                    kind,
                    ground: it.id.clone(),
                    name: name.clone(),
                    class,
                    ways,
                    nodes,
                    width_m: wd,
                    width_source: ws.clone(),
                    width_method: wm.clone(),
                    length,
                    axis,
                    geom: f.clone(),
                    links: vec![],
                },
            });
        }
    }
    lap.lap("the spaces");

    // the links: a path section's ends are the path intersections it touches, both ways
    let boxes: Vec<Option<Rect<f64>>> = recs.iter().map(|r| r.sp.geom.bounding_rect()).collect();
    let rec_index = Index::new(boxes.iter().copied());
    for a in 0..recs.len() {
        let near = NearIndex::new(rings(&recs[a].sp.geom));
        let mut links: Vec<String> = rec_index
            .query(&grow(boxes[a].unwrap(), NEAR_M))
            .into_iter()
            .filter(|&b| b != a && recs[b].sp.kind != recs[a].sp.kind && near.length_within(rings(&recs[b].sp.geom), NEAR_M) >= TOUCH_M)
            .map(|b| recs[b].sp.id.clone())
            .collect();
        links.sort();
        recs[a].sp.links = links;
    }
    lap.lap("the links");
    recs.into_iter().map(|r| r.sp).collect()
}

/// The numbers this crate chooses, for the manifest `urban.meta` (`chosen.<name>`): name, value, what it is.
pub fn chosen() -> Vec<(String, f64, String)> {
    vec![
        ("paths.CUT_HALF_M".to_string(), CUT_HALF_M, "A cut line is drawn this far to each side, then only its piece through the cut point inside the path item is kept.".to_string()),
        ("paths.MIN_PIECE_M2".to_string(), MIN_PIECE_M2, "A piece of a path item smaller than this joins its neighbour (chosen).".to_string()),
        ("paths.MIN_FACE_M2".to_string(), MIN_FACE_M2, "A face smaller than this is a hairline of the noding.".to_string()),
        ("paths.TOUCH_M".to_string(), TOUCH_M, "Two faces are neighbours when their outlines meet along at least this length.".to_string()),
    ]
}
