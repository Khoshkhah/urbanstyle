//! The street spaces of a SimReady build: the Rust port of `src/urbanstyle/simready.py` (docs/notes/steps.md, "2a"; docs/notes/rust-browser.md,
//! step 3). The same rules, in metres, level by level:
//!
//! 1. the spaces: a section (a carriageway and its twin) and a junction each is one space;
//! 2. the roadway parts: the lanes, the islands, and the junction area less what the lanes and islands hold;
//! 3. the walking side: the street less the roadway, cut across at each section end, each piece to the space whose roadway it touches most,
//!    then furnishing strip, sidewalk and frontage from the kerb (or an island where it touches no edge of the street);
//! 4. the crosswalks, from OSM's crossing ways and nodes, cut from the roadway, with their paint;
//! 5. the marks: the kerb, lane lines, the centre line, stop and give-way lines, guide lines.
use geo::{Area, BooleanOps, BoundingRect, Coord, Distance, Euclidean, Intersects, Length, LineString, MultiLineString, Point, Polygon, Rect};
use std::collections::{BTreeMap, HashMap};
use urbanstyle_geo::index::Index;
use urbanstyle_geo::lines;
use urbanstyle_geo::ops::{self, Mp};

pub const CUT_M: f64 = 60.0;
pub const CLEAR_M: f64 = 1.8;
pub const FURNISH_M: f64 = 1.0;
pub const CROSSWALK_M: f64 = 3.0;
pub const ZEBRA_BAR_M: f64 = 0.5;
pub const ZEBRA_GAP_M: f64 = 0.5;
pub const XWALK_MAX_M: f64 = 40.0;
pub const EDGE_TOUCH_M: f64 = 1.0;
/// A piece of the walking side with a mean width under this is not kept.
pub const HAIRLINE_M: f64 = 0.01;
const ROADX: [&str; 6] = ["lane", "junction area", "ring", "cycle lane", "bus lane", "parking"];

// ---- the input: SimReady's rows (read by the Python reference, simready.read_all) and the blocks, corridors and crossings

#[derive(Clone)]
pub struct Carriageway {
    pub id: i64,
    pub way: Option<i64>,
    pub twin: Option<i64>,
    pub shared: bool,
    pub highway: String,
    pub name: Option<String>,
    pub oneway: bool,
    /// The ids of the carriageway's edges, in order.
    pub edges: Vec<i64>,
    pub ring: bool,
    pub inside: Option<i64>,
    pub level: i32,
    pub line: LineString<f64>,
}

#[derive(Clone)]
pub struct Lane {
    pub id: i64,
    pub cid: i64,
    pub n: i64,
    pub role: String,
    pub turn: Option<String>,
    pub w: f64,
    pub method: String,
    pub srcs: Vec<String>,
    pub left: LineString<f64>,
    pub right: LineString<f64>,
    pub geom: Mp,
}

#[derive(Clone)]
pub struct Junction {
    pub id: i64,
    pub nodes: Vec<i64>,
    pub kind: String,
    pub control: Option<String>,
    pub level: i32,
    pub method: String,
    pub area: Mp,
}

#[derive(Clone)]
pub struct Island {
    pub j: Option<i64>,
    pub kind: String,
    pub level: i32,
    pub method: String,
    pub geom: Mp,
}

#[derive(Clone)]
pub struct Stop {
    pub cid: i64,
    pub j: Option<i64>,
    pub method: String,
    pub lines: Vec<LineString<f64>>,
}

#[derive(Clone)]
pub struct Move {
    pub j: i64,
    pub fl: i64,
    pub tl: i64,
    pub fc: i64,
    pub tc: i64,
    pub turn: String,
    /// The vehicles that may use the move.
    pub uses: Vec<String>,
    pub method: String,
    pub lines: Vec<LineString<f64>>,
}

#[derive(Clone)]
pub struct Face {
    pub level: i32,
    pub geom: Mp,
}

#[derive(Clone)]
pub struct CrossingWay {
    pub id: i64,
    pub lines: Vec<LineString<f64>>,
    pub tags: BTreeMap<String, String>,
}

#[derive(Clone)]
pub struct CrossingNode {
    pub id: i64,
    pub tags: BTreeMap<String, String>,
    pub xy: Coord<f64>,
}

#[derive(Clone)]
pub struct Input {
    pub area: Mp,
    pub blocks: Mp,
    pub corridors: Mp,
    pub carriageways: Vec<Carriageway>,
    pub lanes: Vec<Lane>,
    pub junctions: Vec<Junction>,
    pub islands: Vec<Island>,
    pub stops: Vec<Stop>,
    pub moves: Vec<Move>,
    pub faces: Vec<Face>,
    pub crossing_ways: Vec<CrossingWay>,
    pub crossing_nodes: Vec<CrossingNode>,
}

impl Input {
    /// The same input with every polygon oriented (`ops::orient`): the overlays need it.
    pub fn oriented(&self) -> Input {
        let o = ops::orient;
        let mut i = self.clone();
        i.area = o(&i.area);
        i.blocks = o(&i.blocks);
        i.corridors = o(&i.corridors);
        i.lanes.iter_mut().for_each(|l| l.geom = o(&l.geom));
        i.junctions.iter_mut().for_each(|j| j.area = o(&j.area));
        i.islands.iter_mut().for_each(|x| x.geom = o(&x.geom));
        i.faces.iter_mut().for_each(|f| f.geom = o(&f.geom));
        i
    }
}

// ---- the output

#[derive(Clone)]
pub struct Part {
    pub typ: String,
    pub geom: Mp,
    pub lane: Option<i64>,
    pub lane_id: Option<String>,
    pub width_m: Option<f64>,
    pub width_source: String,
    pub width_method: Option<String>,
    pub source: String,
    pub method: String,
    pub reference: String,
    pub direction: Option<String>,
    /// A lane's road: its carriageway's name and class, and whether the road is one-way (`yes` or `no`).
    pub road: Option<String>,
    pub road_class: Option<String>,
    pub oneway: Option<String>,
}

impl Part {
    fn new(typ: &str, geom: Mp, source: &str, method: &str, reference: String) -> Part {
        Part {
            typ: typ.into(),
            geom,
            lane: None,
            lane_id: None,
            width_m: None,
            width_source: "urbanstyle".into(),
            width_method: None,
            source: source.into(),
            method: method.into(),
            reference,
            direction: None,
            road: None,
            road_class: None,
            oneway: None,
        }
    }
}

#[derive(Clone)]
pub struct Mark {
    pub typ: String,
    pub line: LineString<f64>,
    pub source: String,
    pub method: Option<String>,
    pub reference: Option<String>,
}

#[derive(Clone)]
pub struct Unit {
    pub id: String,
    pub subsection: bool,
    pub section: Option<String>,
    pub level: i32,
    pub cws: Vec<i64>,
    pub parts: Vec<Part>,
    pub marks: Vec<Mark>,
    /// The line of a subsection: its carriageway's line in the area, less the junctions.
    pub axis: Option<LineString<f64>>,
}

/// A move from a lane to a lane inside an intersection (`work.turn`).
#[derive(Clone)]
pub struct TurnRow {
    pub unit: String,
    pub level: i32,
    pub from_edge: String,
    pub from_lane: Option<i64>,
    pub to_edge: String,
    pub to_lane: Option<i64>,
    pub turn: Option<String>,
    pub vehicles: String,
    pub lines: Vec<LineString<f64>>,
}

/// The lanes into an intersection (`work.approach`).
#[derive(Clone)]
pub struct ApproachRow {
    pub unit: String,
    pub level: i32,
    pub from_edge: String,
    pub lane: Option<i64>,
    pub moves: i64,
    pub ways: String,
    pub arrow: bool,
    pub no_arrow_because: Option<String>,
}

pub struct Output {
    pub units: Vec<Unit>,
    pub turn_rows: Vec<TurnRow>,
    pub approach_rows: Vec<ApproachRow>,
    /// (intersection, node, level)
    pub junction_rows: Vec<(String, i64, i32)>,
    pub turns: usize,
    pub approaches: usize,
    pub crosswalks: usize,
}

// ---- helpers

fn way_label(w: Option<i64>) -> String {
    w.map_or("None".to_string(), |w| w.to_string())
}

fn mls(l: &LineString<f64>) -> MultiLineString<f64> {
    MultiLineString::new(vec![l.clone()])
}

fn rings(mp: &Mp) -> MultiLineString<f64> {
    MultiLineString::new(mp.0.iter().flat_map(|p| std::iter::once(p.exterior().clone()).chain(p.interiors().iter().cloned())).collect())
}

/// `m` clipped to `poly`, as lines (`lines.intersection(poly)`).
fn clip_to(poly: &Mp, l: &LineString<f64>) -> Vec<LineString<f64>> {
    if poly.0.is_empty() {
        return vec![];
    }
    poly.clip(&mls(l), false).0
}

/// shapely's `lines(...)` of `simready.py`: the lines joined end to end, and those over 0.2 m.
fn merged(ls: Vec<LineString<f64>>) -> Vec<LineString<f64>> {
    lines::dissolve(ls).into_iter().filter(|l| lines::length(l) > 0.2).collect()
}

fn rect_of_mls(m: &MultiLineString<f64>) -> Option<Rect<f64>> {
    m.bounding_rect()
}

fn grow(r: Rect<f64>, d: f64) -> Rect<f64> {
    Rect::new((r.min().x - d, r.min().y - d), (r.max().x + d, r.max().y + d))
}

fn mp1(p: &Polygon<f64>) -> Mp {
    Mp::new(vec![p.clone()])
}

fn empty() -> Mp {
    Mp::new(vec![])
}

fn lane_type(role: &str) -> &'static str {
    match role {
        "bike" => "cycle lane",
        "bus" => "bus lane",
        "parking" => "parking",
        "median" => "island",
        _ => "lane",
    }
}

/// A crossing's paint from its OSM tags (`network.markings`).
pub fn markings(tags: &BTreeMap<String, String>) -> &'static str {
    let mk = tags.get("crossing:markings").map(|s| s.split(';').next().unwrap_or("").trim()).unwrap_or("");
    match mk {
        "yes" | "zebra" => return "zebra",
        "lines" => return "lines",
        "dashes" => return "dashes",
        "ladder" => return "ladder",
        "ladder:skewed" => return "ladder:skewed",
        "skewed" => return "skewed",
        "dots" => return "dots",
        "surface" => return "surface",
        "pictograms" => return "pictograms",
        "no" => return "no",
        _ => {}
    }
    let cr = tags.get("crossing").map(|s| s.as_str());
    if matches!(cr, Some("zebra") | Some("marked") | Some("uncontrolled")) || tags.get("crossing_ref").map(|s| s.as_str()) == Some("zebra") {
        return "zebra";
    }
    if matches!(cr, Some("unmarked") | Some("informal")) {
        return "no";
    }
    "unknown"
}

fn num_f(v: Option<&String>) -> Option<f64> {
    v?.replace('m', "").trim().parse::<f64>().ok()
}

fn mark_rank(mk: &str) -> i32 {
    match mk {
        "zebra" | "ladder" | "ladder:skewed" | "skewed" => 0,
        "lines" | "dashes" | "dots" => 1,
        "surface" | "pictograms" => 2,
        "no" => 4,
        _ => 3,
    }
}

struct Builder {
    units: Vec<Unit>,
}

impl Builder {
    fn part(&mut self, u: usize, p: Part) {
        self.units[u].parts.push(p);
    }
    fn mark(&mut self, u: usize, typ: &str, ls: Vec<LineString<f64>>, source: &str, method: Option<&str>, reference: Option<String>) {
        for l in merged(ls) {
            self.units[u].marks.push(Mark { typ: typ.into(), line: l, source: source.into(), method: method.map(String::from), reference: reference.clone() });
        }
    }
}

pub fn build(inp: &Input) -> Output {
    let mut lap = urbanstyle_geo::Lap::new("division");
    let inp = &inp.oriented();
    lap.lap("orient the input");
    let cw_by_id: HashMap<i64, &Carriageway> = inp.carriageways.iter().map(|c| (c.id, c)).collect();
    let mut lanes_by_cw: HashMap<i64, Vec<&Lane>> = HashMap::new();
    for l in &inp.lanes {
        lanes_by_cw.entry(l.cid).or_default().push(l);
    }

    // ---- 1. the spaces
    let mut b = Builder { units: Vec::new() };
    let mut used: HashMap<String, usize> = HashMap::new();
    let mut new_id = |base: String| {
        let n = used.entry(base.clone()).or_insert(0);
        *n += 1;
        if *n > 1 { format!("{base}.{n}") } else { base }
    };
    let mut jid: HashMap<i64, usize> = HashMap::new();
    let mut juncs: Vec<&Junction> = inp.junctions.iter().collect();
    juncs.sort_by_key(|j| j.id);
    for j in &juncs {
        let id = new_id(format!("i{}-{}", j.level, j.nodes.iter().min().copied().unwrap_or(0)));
        jid.insert(j.id, b.units.len());
        b.units.push(Unit { id, subsection: false, section: None, level: j.level, cws: vec![], parts: vec![], marks: vec![], axis: None });
    }
    let mut unit_of_cw: HashMap<i64, usize> = HashMap::new();
    let mut cws: Vec<&Carriageway> = inp.carriageways.iter().collect();
    cws.sort_by_key(|c| c.id);
    for c in &cws {
        if unit_of_cw.contains_key(&c.id) {
            continue;
        }
        if let Some(ins) = c.inside {
            if let Some(&u) = jid.get(&ins) {
                unit_of_cw.insert(c.id, u);
                b.units[u].cws.push(c.id);
                continue;
            }
        }
        let mut pair = vec![c.id];
        if let Some(t) = c.twin {
            if let Some(tc) = cw_by_id.get(&t) {
                if !unit_of_cw.contains_key(&t) && tc.inside.is_none() {
                    pair.push(t);
                }
            }
        }
        let sid = new_id(format!("s{}-w{}", c.level, way_label(c.way)));
        let u = b.units.len();
        b.units.push(Unit { id: format!("{sid}/1"), subsection: true, section: Some(sid), level: c.level, cws: pair.clone(), parts: vec![], marks: vec![], axis: None });
        for x in pair {
            unit_of_cw.insert(x, u);
        }
    }

    // ---- 2. the roadway parts: the lanes
    let mut lane_list: Vec<&Lane> = inp.lanes.iter().collect();
    lane_list.sort_by_key(|l| l.id);
    for l in &lane_list {
        let Some(&u) = unit_of_cw.get(&l.cid) else { continue };
        if l.geom.0.is_empty() {
            continue;
        }
        let c = cw_by_id[&l.cid];
        let intersection = !b.units[u].subsection;
        let typ = if c.ring && intersection { "ring" } else { lane_type(&l.role) };
        let mut p = Part::new(
            typ,
            l.geom.clone(),
            "simready",
            &l.method,
            format!("c{} lane {} ({}) w{}: {}", l.cid, l.n, l.role, way_label(c.way), l.srcs.join(", ")),
        );
        p.direction = Some(if l.cid == b.units[u].cws[0] || intersection { "forward" } else { "backward" }.into());
        p.lane = Some(l.n);
        p.lane_id = Some(l.id.to_string());
        p.width_m = Some(l.w);
        p.width_source = "simready".into();
        p.width_method = Some(l.method.clone());
        p.road = c.name.clone();
        p.road_class = Some(c.highway.clone());
        p.oneway = Some(if c.oneway { "yes" } else { "no" }.into());
        b.part(u, p);
    }
    let section_parts: Vec<Mp> = b.units.iter().filter(|u| u.subsection).flat_map(|u| u.parts.iter()).filter(|p| !p.geom.0.is_empty()).map(|p| p.geom.clone()).collect();
    let sp_index = Index::of_multipolygons(&section_parts);
    // the junctions: the area less the lanes inside it, the islands and the sections' lanes
    for j in &juncs {
        let u = jid[&j.id];
        for x in inp.islands.iter().filter(|x| x.j == Some(j.id)) {
            let p = Part::new("island", ops::intersection(&x.geom, &inp.area), "simready", &x.method, format!("island {} of junction {}", x.kind, j.id));
            b.part(u, p);
        }
        let area_j = ops::intersection(&j.area, &inp.area);
        let mut taken: Vec<Mp> = b.units[u].parts.iter().map(|p| p.geom.clone()).collect();
        if let Some(r) = area_j.bounding_rect() {
            taken.extend(sp_index.query(&r).into_iter().map(|k| section_parts[k].clone()));
        }
        let rest = ops::difference(&area_j, &ops::union_all(taken.iter()));
        let p = Part::new(
            "junction area",
            rest,
            "simready",
            &j.method,
            format!("junction {} ({}, {})", j.id, j.kind, j.control.clone().unwrap_or_else(|| "None".into())),
        );
        b.part(u, p);
    }

    lap.lap("spaces and the roadway parts");
    // ---- 3. the walking side, level by level
    let mut levels: Vec<i32> = b.units.iter().map(|u| u.level).collect();
    levels.sort();
    levels.dedup();
    for lv in levels {
        let ids: Vec<usize> = (0..b.units.len()).filter(|&u| b.units[u].level == lv).collect();
        let road: Vec<Mp> = (0..b.units.len())
            .map(|u| if b.units[u].level == lv { ops::union_all(b.units[u].parts.iter().map(|p| &p.geom)) } else { empty() })
            .collect();
        let road_all = ops::union_all(ids.iter().map(|&u| &road[u]));
        let street = if lv == 0 {
            ops::difference(&ops::difference(&inp.area, &inp.blocks), &inp.corridors)
        } else {
            let fs: Vec<&Mp> = inp.faces.iter().filter(|f| f.level == lv).map(|f| &f.geom).collect();
            ops::intersection(&ops::union_all(fs.into_iter()), &inp.area)
        };
        let realm = ops::difference(&street, &road_all);
        if realm.0.is_empty() {
            continue;
        }
        // the cuts: each section's two ends, across the street (its first and last lane's ends joined, run CUT_M to each side)
        let realm_b = ops::buffer(&realm, 0.01);
        let rb_index = urbanstyle_geo::index::SegIndex::new(&realm_b);
        let mut cuts: Vec<LineString<f64>> = Vec::new();
        for &u in &ids {
            if !b.units[u].subsection {
                continue;
            }
            for cid in b.units[u].cws.clone() {
                let mut ls: Vec<&&Lane> = lanes_by_cw.get(&cid).map(|v| v.iter().filter(|l| lines::length(&l.left) > 0.0).collect()).unwrap_or_default();
                ls.sort_by_key(|l| l.n);
                let (Some(first), Some(last)) = (ls.first(), ls.last()) else { continue };
                for k in [0usize, 1] {
                    let a = if k == 0 { first.left.0[0] } else { *first.left.0.last().unwrap() };
                    let bb = if k == 0 { last.right.0[0] } else { *last.right.0.last().unwrap() };
                    let d = (bb.x - a.x).hypot(bb.y - a.y);
                    if d < 0.5 {
                        continue;
                    }
                    let (ux, uy) = ((bb.x - a.x) / d, (bb.y - a.y) / d);
                    let cut = LineString::new(vec![Coord { x: a.x - ux * CUT_M, y: a.y - uy * CUT_M }, Coord { x: bb.x + ux * CUT_M, y: bb.y + uy * CUT_M }]);
                    let seg = LineString::new(vec![a, bb]);
                    // (only the pieces that start at this end: a cut does not run on through the next street's sidewalk)
                    for q in rb_index.clip(cut.0[0], cut.0[1]) {
                        if Euclidean.distance(&q, &seg) < 1.5 {
                            cuts.push(q);
                        }
                    }
                }
            }
        }
        lap.lap("  walking side: street, realm, cuts");
        let pieces: Vec<Polygon<f64>> = if cuts.is_empty() { realm.0.clone() } else { ops::slice(&realm, &cuts).0 }
            .into_iter()
            .filter(|q| q.unsigned_area() > 0.05)
            // (a piece thinner than a centimetre on average is a hairline between SimReady's face and its lanes, not a walking side: the
            // Python reference snaps to a 1 cm grid, so those do not reach its kerb)
            .filter(|q| 2.0 * q.unsigned_area() / Euclidean.length(q.exterior()).max(1e-9) >= HAIRLINE_M)
            .collect();
        lap.lap("  walking side: slice");
        let road_b = ops::buffer(&road_all, 0.05);
        lap.lap("    road buffer");
        let road_idx = urbanstyle_geo::index::SegIndex::new(&road_b);
        let edge_lines = MultiLineString::new(rings(&street).0.iter().flat_map(|r| road_idx.clip_line(r, false)).collect());
        lap.lap("    edge lines");
        // (the length of the piece's outline within 0.3 m of an edge of the street, from the segments: no buffer of 100,000 pieces)
        let edge_near = urbanstyle_geo::index::NearIndex::new(edge_lines.0.iter());
        let along_edge = |q: &Polygon<f64>| -> f64 { edge_near.length_within(std::iter::once(q.exterior()).chain(q.interiors()), 0.3) };
        lap.lap("  walking side: the edge of the street");
        let bnd: Vec<MultiLineString<f64>> = (0..b.units.len()).map(|u| rings(&road[u])).collect();
        let owners: Vec<usize> = ids.iter().copied().filter(|&u| !road[u].0.is_empty()).collect();
        // (the length of each unit's roadway outline within 0.3 m of the piece, from the segments, tagged by unit)
        let owner_near = urbanstyle_geo::index::NearIndex::tagged(owners.iter().flat_map(|&u| bnd[u].0.iter().map(move |l| (u, l))));
        lap.lap("    owner index");
        let mut share: BTreeMap<usize, Vec<Polygon<f64>>> = BTreeMap::new();
        for q in &pieces {
            let mut best: Option<(f64, &str, usize)> = None;
            for (u, t) in owner_near.covered_by_tag(std::iter::once(q.exterior()).chain(q.interiors()), 0.3) {
                if t > 0.05 && best.map_or(true, |(bt, bid, _)| t > bt || (t == bt && b.units[u].id.as_str() > bid)) {
                    best = Some((t, b.units[u].id.as_str(), u));
                }
            }
            let owner = match best {
                Some((_, _, u)) => u,
                // (a piece that touches no roadway goes to the unit nearest to it)
                None => match owner_near.nearest_tag(q.exterior().0.iter().copied()) {
                    Some(u) => u,
                    None => continue,
                },
            };
            share.entry(owner).or_default().push(q.clone());
        }
        lap.lap("  walking side: owners");
        for (u, qs) in share {
            let own = ops::union_all(qs.iter().map(mp1).collect::<Vec<_>>().iter());
            let own_b = ops::buffer(&own, 0.05);
            let kerb = if own_b.0.is_empty() {
                MultiLineString::new(vec![])
            } else {
                let own_idx = urbanstyle_geo::index::SegIndex::new(&own_b);
                MultiLineString::new(bnd[u].0.iter().flat_map(|r| own_idx.clip_line(r, true)).collect())
            };
            b.mark(u, "kerb", kerb.0.clone(), "simready", Some("the roadway's edge"), Some("the edge of SimReady's lanes and junction area facing the pedestrian side".into()));
            let kb = if kerb.0.is_empty() { empty() } else { ops::normalize(geo::Buffer::buffer(&kerb, FURNISH_M)) };
            let kc = if kerb.0.is_empty() { empty() } else { ops::normalize(geo::Buffer::buffer(&kerb, FURNISH_M + CLEAR_M)) };
            // (the three bands of all the pieces of the unit at once, then each part to the piece it lies in: an overlay of each piece with
            // the buffer of the whole kerb took the time of all its edges for each piece)
            let mut keep: Vec<&Polygon<f64>> = Vec::new();
            for q in &own.0 {
                if along_edge(q) < EDGE_TOUCH_M {
                    b.part(u, Part::new("island", mp1(q), "urbanstyle", "derived", "between roadways: it touches no edge of the street".into()));
                } else {
                    keep.push(q);
                }
            }
            if keep.is_empty() {
                continue;
            }
            let own_keep = Mp::new(keep.iter().map(|q| (*q).clone()).collect());
            let furnishing = ops::intersection(&own_keep, &kb);
            let sidewalk = ops::difference(&ops::intersection(&own_keep, &kc), &kb);
            let frontage = ops::difference(&own_keep, &kc);
            let boxes = urbanstyle_geo::index::Index::new(keep.iter().map(|q| q.bounding_rect()));
            let mut by_piece: [Vec<Vec<Polygon<f64>>>; 3] = [vec![Vec::new(); keep.len()], vec![Vec::new(); keep.len()], vec![Vec::new(); keep.len()]];
            for (t, x) in [&furnishing, &sidewalk, &frontage].into_iter().enumerate() {
                for r in &x.0 {
                    let (Some(bb), Some(ip)) = (r.bounding_rect(), geo::InteriorPoint::interior_point(r)) else { continue };
                    if let Some(k) = boxes.query(&bb).into_iter().find(|&k| geo::Contains::contains(keep[k], &ip)) {
                        by_piece[t][k].push(r.clone());
                    }
                }
            }
            for k in 0..keep.len() {
                for (t, (typ, w)) in [("furnishing", Some(FURNISH_M)), ("sidewalk", Some(CLEAR_M)), ("frontage", None)].into_iter().enumerate() {
                    let x = Mp::new(std::mem::take(&mut by_piece[t][k]));
                    if ops::area(&x) > 0.05 {
                        let mut p = Part::new(typ, x, "urbanstyle", "derived", "the street less SimReady's roadway, to the space whose roadway it touches most".into());
                        p.width_m = w;
                        p.width_method = w.map(|_| "chosen".to_string());
                        b.part(u, p);
                    }
                }
            }
        }
        lap.lap("  walking side: kerb and bands");
    }

    lap.lap("walking side: end");
    // ---- 4. the crosswalks
    let n_xw = crosswalks(inp, &mut b, &cw_by_id, &lanes_by_cw);

    lap.lap("crosswalks");
    // ---- 5. the marks
    let mut by_cw: Vec<(&i64, &Vec<&Lane>)> = lanes_by_cw.iter().collect();
    by_cw.sort_by_key(|(c, _)| **c);
    for (cid, ls) in by_cw {
        let Some(&u) = unit_of_cw.get(cid) else { continue };
        let mut ls: Vec<&Lane> = ls.clone();
        ls.sort_by_key(|l| l.n);
        let drive: Vec<&&Lane> = ls.iter().filter(|l| matches!(l.role.as_str(), "through" | "pocket" | "merge" | "bus" | "bike")).collect();
        for w in drive.windows(2) {
            if w[1].n == w[0].n + 1 {
                b.mark(u, "lane line", clip_to(&inp.area, &w[0].right), "simready", Some(&w[0].method), Some(format!("c{}: between lanes {} and {}", cid, w[0].n, w[1].n)));
            }
        }
        let c = cw_by_id[cid];
        if c.shared && c.twin.map_or(false, |t| cw_by_id.contains_key(&t)) && b.units[u].subsection && *cid == b.units[u].cws[0] && !ls.is_empty() {
            b.mark(u, "centre line", clip_to(&inp.area, &ls[0].left), "simready", Some(&ls[0].method), Some(format!("c{} and c{}: the line between the two directions", cid, c.twin.unwrap())));
        }
    }
    let juncs_by_id: HashMap<i64, &Junction> = inp.junctions.iter().map(|j| (j.id, j)).collect();
    for s in &inp.stops {
        let Some(j) = s.j.and_then(|j| juncs_by_id.get(&j)) else { continue };
        let typ = match j.control.as_deref() {
            Some("signal") | Some("stop") => "stop line",
            Some("yield") => "give-way line",
            _ => continue,
        };
        let Some(&u) = unit_of_cw.get(&s.cid) else { continue };
        let ls: Vec<LineString<f64>> = s.lines.iter().flat_map(|l| clip_to(&inp.area, l)).collect();
        b.mark(u, typ, ls, "simready", Some(&s.method), Some(format!("c{} at junction {} ({})", s.cid, j.id, j.control.clone().unwrap_or_default())));
    }
    for m in &inp.moves {
        if let Some(&u) = jid.get(&m.j) {
            let ls: Vec<LineString<f64>> = m.lines.iter().flat_map(|l| clip_to(&inp.area, l)).collect();
            b.mark(u, "guide line", ls, "simready", Some(&m.method), Some(format!("c{} to c{} ({})", m.fc, m.tc, m.turn)));
        }
    }

    lap.lap("marks");
    // ---- 6. the rows: a part under 0.05 m2 is left out, a space under 0.5 m2 too; the axis of a subsection stops at the junctions
    let mut junc_road: BTreeMap<i32, Vec<Mp>> = BTreeMap::new();
    for u in b.units.iter().filter(|u| !u.subsection) {
        for p in u.parts.iter().filter(|p| matches!(p.typ.as_str(), "junction area" | "lane" | "ring" | "island")) {
            junc_road.entry(u.level).or_default().push(p.geom.clone());
        }
    }
    let junc_index: BTreeMap<i32, Index> = junc_road.iter().map(|(l, v)| (*l, Index::of_multipolygons(v))).collect();
    let mut written: Vec<bool> = vec![false; b.units.len()];
    for (ui, u) in b.units.iter_mut().enumerate() {
        u.parts.retain(|p| ops::area(&p.geom) > 0.05);
        let geom = ops::union_all(u.parts.iter().map(|p| &p.geom));
        if ops::area(&geom) <= 0.5 {
            u.parts.clear();
            continue;
        }
        written[ui] = true;
        if u.subsection {
            let c = cw_by_id[&u.cws[0]];
            let inside: Vec<LineString<f64>> = clip_to(&inp.area, &c.line);
            let mut axis: Vec<LineString<f64>> = Vec::new();
            for l in &inside {
                let jp: Vec<&Mp> = match (junc_index.get(&u.level), junc_road.get(&u.level)) {
                    (Some(ix), Some(v)) => ix.query(&l.bounding_rect().unwrap()).into_iter().map(|k| &v[k]).collect(),
                    _ => vec![],
                };
                if jp.is_empty() {
                    axis.push(l.clone());
                } else {
                    axis.extend(ops::union_all(jp.into_iter()).clip(&mls(l), true).0);
                }
            }
            let axis = merged(axis);
            u.axis = axis.into_iter().max_by(|a, b| lines::length(a).partial_cmp(&lines::length(b)).unwrap()).or_else(|| inside.into_iter().max_by(|a, b| lines::length(a).partial_cmp(&lines::length(b)).unwrap()));
        }
    }
    let mut junction_rows = Vec::new();
    for j in &juncs {
        let u = jid[&j.id];
        if written[u] {
            junction_rows.extend(j.nodes.iter().map(|&n| (b.units[u].id.clone(), n, j.level)));
        }
    }
    let lane_by_id: HashMap<i64, &Lane> = inp.lanes.iter().map(|l| (l.id, l)).collect();
    let edge_end = |cid: i64, last: bool| -> String {
        match cw_by_id.get(&cid) {
            Some(c) if !c.edges.is_empty() => (if last { c.edges[c.edges.len() - 1] } else { c.edges[0] }).to_string(),
            _ => format!("c{cid}"),
        }
    };
    // the moves and the lanes into each junction: one approach for each (space, edge it comes from, lane), counting its moves
    let mut turn_rows: Vec<TurnRow> = Vec::new();
    let mut approaches: Vec<((usize, String, Option<i64>), (i64, std::collections::BTreeSet<String>, Option<String>))> = Vec::new();
    for m in &inp.moves {
        let Some(&u) = jid.get(&m.j) else { continue };
        if !written[u] || m.lines.is_empty() {
            continue;
        }
        let (fl, tl) = (lane_by_id.get(&m.fl), lane_by_id.get(&m.tl));
        let level = juncs.iter().find(|j| j.id == m.j).map_or(0, |j| j.level);
        let from_edge = edge_end(m.fc, true);
        turn_rows.push(TurnRow {
            unit: b.units[u].id.clone(),
            level,
            from_edge: from_edge.clone(),
            from_lane: fl.map(|l| l.n),
            to_edge: edge_end(m.tc, false),
            to_lane: tl.map(|l| l.n),
            turn: Some(m.turn.clone()),
            vehicles: m.uses.join(";"),
            lines: m.lines.clone(),
        });
        let key = (u, from_edge, fl.map(|l| l.n));
        match approaches.iter_mut().find(|(k, _)| *k == key) {
            Some((_, v)) => {
                v.0 += 1;
                v.1.insert(m.turn.clone());
            }
            None => approaches.push((key, (1, std::iter::once(m.turn.clone()).collect(), fl.and_then(|l| l.turn.clone())))),
        }
    }
    let approach_rows: Vec<ApproachRow> = approaches
        .into_iter()
        .map(|((u, e, n), (k, w, t))| {
            let arrow = t.as_deref().map_or(false, |t| !t.is_empty() && t != "none");
            ApproachRow { unit: b.units[u].id.clone(), level: b.units[u].level, from_edge: e, lane: n, moves: k, ways: w.into_iter().collect::<Vec<_>>().join(";"), arrow, no_arrow_because: if arrow { None } else { Some("SimReady gives no turn arrow".into()) } }
        })
        .collect();
    let (turns, n_approaches) = (turn_rows.len(), approach_rows.len());
    lap.lap("rows");
    Output { units: b.units.into_iter().enumerate().filter(|(i, _)| written[*i]).map(|(_, u)| u).collect(), turn_rows, approach_rows, junction_rows, turns, approaches: n_approaches, crosswalks: n_xw }
}

/// The crosswalks (`network.py`'s rules, 8a): OSM's crossing ways over the roadway, and a crossing node on a street with no crossing way
/// at it. Each is a part of its own, cut from the lanes and junction areas it lies on, with its paint. Returns how many.
fn crosswalks(inp: &Input, b: &mut Builder, cw_by_id: &HashMap<i64, &Carriageway>, lanes_by_cw: &HashMap<i64, Vec<&Lane>>) -> usize {
    // the road polygon of each space at level 0, from an index (the roadway is one connected polygon: its buffer for each crossing is slow)
    let road0: Vec<(usize, Mp)> = (0..b.units.len())
        .filter(|&u| b.units[u].level == 0)
        .map(|u| (u, ops::union_all(b.units[u].parts.iter().filter(|p| ROADX.contains(&p.typ.as_str())).map(|p| &p.geom))))
        .filter(|(_, m)| !m.0.is_empty())
        .collect();
    let road_index = Index::of_multipolygons(&road0.iter().map(|(_, m)| m.clone()).collect::<Vec<_>>());
    let cw0: Vec<&Carriageway> = inp.carriageways.iter().filter(|c| c.level == 0 && c.line.0.len() >= 2).collect();
    let cw_index = Index::new(cw0.iter().map(|c| c.line.bounding_rect()));
    let lane_u: HashMap<i64, Mp> = lanes_by_cw.iter().map(|(c, ls)| (*c, ops::union_all(ls.iter().map(|l| &l.geom)))).collect();
    let way_lines: Vec<MultiLineString<f64>> = inp.crossing_ways.iter().map(|w| MultiLineString::new(w.lines.clone())).collect();
    let way_index = Index::new(way_lines.iter().map(rect_of_mls));

    let crosses_road = |seg: &LineString<f64>| -> bool {
        let Some(r) = seg.bounding_rect() else { return false };
        let mut ks: Vec<usize> = cw_index.query(&r).into_iter().filter(|&k| cw0[k].line.intersects(seg)).collect();
        ks.sort();
        let Some(&k) = ks.first() else { return lines::length(seg) <= XWALK_MAX_M };
        let ln = &cw0[k].line;
        // the first point where the two lines cross
        let mut mid: Option<Coord<f64>> = None;
        'o: for a in ln.lines() {
            for c in seg.lines() {
                if let Some(geo::LineIntersection::SinglePoint { intersection, .. }) = geo::algorithm::line_intersection::line_intersection(a, c) {
                    mid = Some(intersection);
                    break 'o;
                }
            }
        }
        let mid = mid.unwrap_or(ln.0[0]);
        let (s_, t_) = (lines::project(ln, mid), lines::project(seg, mid));
        let (a_, b_) = (lines::interpolate(ln, (s_ - 1.0).max(0.0)).unwrap(), lines::interpolate(ln, (s_ + 1.0).min(lines::length(ln))).unwrap());
        let (xa, xb) = (lines::interpolate(seg, (t_ - 1.0).max(0.0)).unwrap(), lines::interpolate(seg, (t_ + 1.0).min(lines::length(seg))).unwrap());
        let (h1, h2) = ((xb.x - xa.x).hypot(xb.y - xa.y).max(1e-12), (b_.x - a_.x).hypot(b_.y - a_.y).max(1e-12));
        ((xb.x - xa.x) * (b_.x - a_.x) + (xb.y - xa.y) * (b_.y - a_.y)).abs() / (h1 * h2) < 30f64.to_radians().cos()
    };

    struct Xw {
        geom: Mp,
        mk: &'static str,
        reference: String,
        seg: LineString<f64>,
        w: f64,
    }
    let mut xw: Vec<Xw> = Vec::new();
    for (wi, cwy) in inp.crossing_ways.iter().enumerate() {
        let w = num_f(cwy.tags.get("width")).unwrap_or(CROSSWALK_M);
        let x = &way_lines[wi];
        let Some(xr) = rect_of_mls(x) else { continue };
        let near: Vec<Mp> = road_index.query(&grow(xr, 0.3 + w)).into_iter().map(|k| road0[k].1.clone()).collect();
        let near_rw = ops::union_all(near.iter());
        if near_rw.0.is_empty() {
            continue;
        }
        let nb = ops::buffer(&near_rw, 0.3);
        for seg in nb.clip(x, false).0 {
            if lines::length(&seg) >= 1.0 && crosses_road(&seg) {
                xw.push(Xw {
                    geom: ops::intersection(&ops::buffer_line_flat(&seg, w / 2.0), &near_rw),
                    mk: markings(&cwy.tags),
                    reference: format!("w{}", cwy.id),
                    seg,
                    w,
                });
            }
        }
    }
    for n in &inp.crossing_nodes {
        let p = Point::from(n.xy);
        let near_way = way_index.query(&Rect::new((n.xy.x - 2.0, n.xy.y - 2.0), (n.xy.x + 2.0, n.xy.y + 2.0))).into_iter().any(|k| way_lines[k].0.iter().any(|l| Euclidean.distance(&p, l) < 2.0));
        if near_way {
            continue; // (a crossing way maps it)
        }
        let mut bands: Vec<Mp> = Vec::new();
        let mut seg0: Option<LineString<f64>> = None;
        for k in cw_index.query(&Rect::new((n.xy.x - 1.0, n.xy.y - 1.0), (n.xy.x + 1.0, n.xy.y + 1.0))) {
            let c = cw0[k];
            if Euclidean.distance(&p, &c.line) > 1.0 {
                continue;
            }
            let s_ = lines::project(&c.line, n.xy);
            let seg = lines::substring(&c.line, (s_ - CROSSWALK_M / 2.0).max(0.0), (s_ + CROSSWALK_M / 2.0).min(lines::length(&c.line)));
            if lines::length(&seg) < 0.5 {
                continue;
            }
            let mut rd: Vec<&Mp> = vec![];
            if let Some(m) = lane_u.get(&c.id) {
                rd.push(m);
            }
            if let Some(m) = c.twin.and_then(|t| lane_u.get(&t)) {
                rd.push(m);
            }
            bands.push(ops::intersection(&ops::buffer_line_flat(&seg, 25.0), &ops::union_all(rd.into_iter())));
            if seg0.as_ref().map_or(true, |s| lines::length(s) < lines::length(&seg)) {
                seg0 = Some(seg);
            }
        }
        let Some(seg0) = seg0 else { continue };
        let across = ops::union_all(bands.iter());
        if across.0.is_empty() {
            continue;
        }
        let (a, z) = (seg0.0[0], *seg0.0.last().unwrap());
        let h = (z.x - a.x).hypot(z.y - a.y).max(1e-12);
        let (nx, ny) = (-(z.y - a.y) / h, (z.x - a.x) / h);
        let walk_line = LineString::new(vec![Coord { x: n.xy.x - nx * 30.0, y: n.xy.y - ny * 30.0 }, Coord { x: n.xy.x + nx * 30.0, y: n.xy.y + ny * 30.0 }]);
        let walk = clip_to(&ops::buffer(&across, 0.1), &walk_line).into_iter().max_by(|a, b| lines::length(a).partial_cmp(&lines::length(b)).unwrap()).unwrap_or(seg0);
        xw.push(Xw { geom: across, mk: markings(&n.tags), reference: format!("n{}", n.id), seg: walk, w: CROSSWALK_M });
    }
    // two crosswalks on one spot: the marked one keeps its shape, the next gives way to it
    xw.sort_by(|x, y| (mark_rank(x.mk), -ops::area(&x.geom)).partial_cmp(&(mark_rank(y.mk), -ops::area(&y.geom))).unwrap());
    let mut taken: Vec<Mp> = Vec::new();
    let mut n_xw = 0;
    for x in xw {
        let near: Vec<&Mp> = taken.iter().filter(|t| match (t.bounding_rect(), x.geom.bounding_rect()) {
            (Some(a), Some(c)) => a.intersects(&c),
            _ => false,
        }).collect();
        let geom = if near.is_empty() { x.geom.clone() } else { ops::difference(&x.geom, &ops::union_all(near.into_iter())) };
        if ops::area(&geom) < 0.5 {
            continue;
        }
        let mut owned = false;
        let Some(xr) = geom.bounding_rect() else { continue };
        for k in road_index.query(&xr) {
            let (u, rd) = (&road0[k].0, &road0[k].1);
            let piece = ops::intersection(&geom, rd);
            if ops::area(&piece) < 0.5 {
                continue;
            }
            owned = true;
            let reference = if x.mk != "unknown" { format!("{} crossing:markings={}", x.reference, x.mk) } else { format!("{}: a crossing, its paint not mapped", x.reference) };
            let mapped = x.w != CROSSWALK_M;
            let mut p = Part::new("crosswalk", piece.clone(), "osm", if mapped { "mapped" } else { "derived" }, reference.clone());
            p.width_m = Some(x.w);
            p.width_source = if mapped { "osm" } else { "urbanstyle" }.into();
            p.width_method = Some(if mapped { "mapped" } else { "chosen" }.into());
            b.part(*u, p);
            let pb = ops::buffer(&piece, 0.01);
            if matches!(x.mk, "zebra" | "ladder" | "ladder:skewed" | "skewed") {
                // bars square to the walking direction, ZEBRA_GAP_M apart
                let (a, z) = (x.seg.0[0], *x.seg.0.last().unwrap());
                let h = (z.x - a.x).hypot(z.y - a.y).max(1e-12);
                let (ux, uy) = ((z.x - a.x) / h, (z.y - a.y) / h);
                let mut d = ZEBRA_BAR_M / 2.0;
                let total = lines::length(&x.seg);
                while d < total {
                    if let Some(c) = lines::interpolate(&x.seg, d) {
                        let bar = LineString::new(vec![Coord { x: c.x - uy * x.w / 2.0, y: c.y + ux * x.w / 2.0 }, Coord { x: c.x + uy * x.w / 2.0, y: c.y - ux * x.w / 2.0 }]);
                        b.mark(*u, "zebra", clip_to(&pb, &bar), "osm", Some("mapped"), Some(format!("{} crossing:markings={}", x.reference, x.mk)));
                    }
                    d += ZEBRA_BAR_M + ZEBRA_GAP_M;
                }
            }
            if matches!(x.mk, "lines" | "dashes" | "ladder" | "ladder:skewed" | "skewed" | "dots") {
                for side in [x.w / 2.0 - 0.1, -x.w / 2.0 + 0.1] {
                    b.mark(*u, "crossing line", clip_to(&pb, &lines::offset(&x.seg, side)), "osm", Some("mapped"), Some(format!("{} crossing:markings={}", x.reference, x.mk)));
                }
            }
        }
        if owned {
            taken.push(geom);
            n_xw += 1;
        }
    }
    // the roadway gives way to the crosswalks: no two parts of one space overlap
    if !taken.is_empty() {
        let xs = Index::of_multipolygons(&taken);
        for u in b.units.iter_mut().filter(|u| u.level == 0) {
            for p in u.parts.iter_mut().filter(|p| ROADX.contains(&p.typ.as_str())) {
                let Some(r) = p.geom.bounding_rect() else { continue };
                let near: Vec<&Mp> = xs.query(&r).into_iter().map(|k| &taken[k]).collect();
                if !near.is_empty() {
                    p.geom = ops::difference(&p.geom, &ops::union_all(near.into_iter()));
                }
            }
        }
    }
    let _ = cw_by_id;
    n_xw
}

/// The numbers this crate chooses, for the manifest `urban.meta` (`chosen.<name>`): name, value, what it is.
pub fn chosen() -> Vec<(String, f64, String)> {
    vec![
        ("division.CUT_M".to_string(), CUT_M, "a chosen value".to_string()),
        ("division.CLEAR_M".to_string(), CLEAR_M, "a chosen value".to_string()),
        ("division.FURNISH_M".to_string(), FURNISH_M, "a chosen value".to_string()),
        ("division.CROSSWALK_M".to_string(), CROSSWALK_M, "a chosen value".to_string()),
        ("division.ZEBRA_BAR_M".to_string(), ZEBRA_BAR_M, "a chosen value".to_string()),
        ("division.ZEBRA_GAP_M".to_string(), ZEBRA_GAP_M, "a chosen value".to_string()),
        ("division.XWALK_MAX_M".to_string(), XWALK_MAX_M, "a chosen value".to_string()),
        ("division.EDGE_TOUCH_M".to_string(), EDGE_TOUCH_M, "a chosen value".to_string()),
        ("division.HAIRLINE_M".to_string(), HAIRLINE_M, "A piece of the walking side with a mean width under this is not kept.".to_string()),
    ]
}
