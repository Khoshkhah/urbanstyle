//! The input of the division step from SimReady's Parquet files (`<area>-rust/*.parquet`) and duckOSM's edges: what the Python
//! `simready.read_all` selects from `sim.*` (the streets' carriageways, their lanes, the junctions, islands, stop lines, moves and the
//! faces of the other levels, all that reach into the area). The blocks, the corridors and the crossings come from the other readers.
use crate::{table::Table, wkb};
use geo::{BoundingRect, Intersects, LineString};
use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;
use urbanstyle_division as d;
use urbanstyle_geo::ops::{self, Mp};

/// The road classes that are streets (`network.STREET`); a `_link` of one is a street too.
pub const STREET: [&str; 8] = ["motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "living_street"];
/// urbanstyle's levels (`container.CLAMP`): SimReady's lower tunnels go to the lowest.
pub const LEVELS: (i32, i32) = (-2, 2);
/// The grid of the Python overlay that cuts a lane to the area (`shapely.intersection(.., grid_size=0.01)`).
const GRID_M: f64 = 0.01;

/// duckOSM's driving edges: the way and the length of each edge, and the edges that carry a `service=*` kind.
pub struct Edges {
    pub way: BTreeMap<i64, (i64, f64)>,
    pub service: BTreeSet<i64>,
}

impl Edges {
    /// `edges_driving.parquet` of duckOSM's pass-0 folder.
    pub fn read(path: &Path) -> Result<Edges, String> {
        let t = Table::open(path)?;
        let (id, osm, len, service) = (t.i64s("edge_id"), t.i64s("osm_id"), t.f64s("length_m"), t.strs("service"));
        let mut e = Edges { way: BTreeMap::new(), service: BTreeSet::new() };
        for i in 0..id.len() {
            let Some(k) = id[i] else { continue };
            e.way.insert(k, (osm[i].unwrap_or(0), len[i].unwrap_or(0.0)));
            if service[i].is_some() {
                e.service.insert(k);
            }
        }
        Ok(e)
    }
}

/// blocks.street_sql's rule on a SimReady carriageway: a street class with its links, or a service road with a street's name and no
/// `service=*` kind. An unnamed service road, a car park's aisle or a drive, is no street, though SimReady gives it lanes.
pub fn is_street(highway: &str, name: Option<&str>, edges: &[i64], service: &BTreeSet<i64>) -> bool {
    STREET.contains(&highway.strip_suffix("_link").unwrap_or(highway))
        || (highway == "service" && name.map_or(false, |n| !n.is_empty()) && !edges.iter().any(|e| service.contains(e)))
}

pub fn level_of(x: Option<i64>) -> i32 {
    (x.unwrap_or(0) as i32).clamp(LEVELS.0, LEVELS.1)
}

pub struct Sim {
    pub carriageways: Vec<d::Carriageway>,
    pub lanes: Vec<d::Lane>,
    pub junctions: Vec<d::Junction>,
    pub islands: Vec<d::Island>,
    pub stops: Vec<d::Stop>,
    pub moves: Vec<d::Move>,
    pub faces: Vec<d::Face>,
}

fn blobs(t: &Table, col: &str) -> Vec<Option<wkb::Geom>> {
    t.blobs(col).into_iter().map(|b| b.and_then(|b| wkb::parse(&b))).collect()
}

fn reaches_lines(area: &Mp, l: &[LineString<f64>]) -> bool {
    l.iter().any(|x| x.bounding_rect().is_some() && area.intersects(x))
}

fn reaches_mp(area: &Mp, m: &Mp) -> bool {
    m.bounding_rect().is_some() && area.intersects(m)
}

/// Python's `round(x, 2)`.
fn round2(x: f64) -> f64 {
    (x * 100.0).round_ties_even() / 100.0
}

pub fn read(dir: &Path, edges: &Edges, area: &Mp) -> Result<Sim, String> {
    let open = |f: &str| Table::open(&dir.join(f));
    let rows = |t: &Table, kind: &str| -> Vec<usize> { t.strs("table").iter().enumerate().filter(|(_, k)| k.as_deref() == Some(kind)).map(|(i, _)| i).collect() };

    // ---- the carriageways: the streets', those that reach into the area
    let t = open("reference-line.parquet")?;
    let (id, twin, shared, hw, name, oneway, ring, inside, level, from, to) = (
        t.i64s("carriageway_id"),
        t.i64s("twin_carriageway_id"),
        t.bools("shared_line"),
        t.strs("highway"),
        t.strs("name"),
        t.bools("oneway"),
        t.i64s("roundabout_id"),
        t.i64s("inside_junction_id"),
        t.i64s("level"),
        t.i64s("from_node_id"),
        t.i64s("to_node_id"),
    );
    let eids = t.list_i64s("edge_ids");
    let lines = blobs(&t, "reference_line");
    let mut carriageways = Vec::new();
    let mut ends: BTreeSet<i64> = BTreeSet::new();
    for i in rows(&t, "carriageway") {
        let (Some(cid), Some(wkb::Geom::Lines(l))) = (id[i], lines[i].as_ref().map(|g| match g {
            wkb::Geom::Lines(l) => wkb::Geom::Lines(l.clone()),
            _ => wkb::Geom::Lines(vec![]),
        })) else {
            continue;
        };
        if l.len() != 1 || !reaches_lines(area, &l) {
            continue;
        }
        let es = eids[i].clone().unwrap_or_default();
        let h = hw[i].clone().unwrap_or_default();
        if !is_street(&h, name[i].as_deref(), &es, &edges.service) {
            continue;
        }
        // the way of the longest of its edges (the first of equal ones)
        let mut best: Option<(i64, f64)> = None;
        for e in es.iter().filter_map(|e| edges.way.get(e)) {
            if best.map_or(true, |b| e.1 > b.1) {
                best = Some(*e);
            }
        }
        ends.extend(from[i]);
        ends.extend(to[i]);
        carriageways.push(d::Carriageway {
            id: cid,
            way: best.map(|b| b.0),
            twin: twin[i],
            shared: shared[i].unwrap_or(false),
            highway: h,
            name: name[i].clone(),
            oneway: oneway[i].unwrap_or(false),
            edges: es,
            ring: ring[i].is_some(),
            inside: inside[i],
            level: level_of(level[i]),
            line: l.into_iter().next().unwrap(),
        });
    }
    let street_ids: BTreeSet<i64> = carriageways.iter().map(|c| c.id).collect();

    // ---- the lanes of those carriageways, each cut to the area
    let wp = open("width-profiles.parquet")?;
    let lb = open("lane-boundaries.parquet")?;
    let (lid, bl, br) = (lb.i64s("lane_id"), blobs(&lb, "boundary_left"), blobs(&lb, "boundary_right"));
    let mut bounds: BTreeMap<i64, usize> = BTreeMap::new();
    for (k, l) in lid.iter().enumerate() {
        if let Some(l) = l {
            bounds.insert(*l, k);
        }
    }
    let (lane_id, cid, num, role, turn, w0, w1, method, srcs) = (
        wp.i64s("lane_id"),
        wp.i64s("carriageway_id"),
        wp.i64s("lane_num"),
        wp.strs("role"),
        wp.strs("turn"),
        wp.f64s("width_start_m"),
        wp.f64s("width_end_m"),
        wp.strs("ev_method"),
        wp.list_strs("ev_source_ids"),
    );
    let mut lanes = Vec::new();
    for i in rows(&wp, "lane") {
        let (Some(l), Some(c)) = (lane_id[i], cid[i]) else { continue };
        if !street_ids.contains(&c) {
            continue;
        }
        let Some(&k) = bounds.get(&l) else { continue };
        let (Some(wkb::Geom::Lines(mut left)), Some(wkb::Geom::Lines(mut right))) = (bl[k].as_ref().map(clone_geom), br[k].as_ref().map(clone_geom)) else { continue };
        if left.len() != 1 || right.len() != 1 {
            continue;
        }
        let (left, right) = (left.pop().unwrap(), right.pop().unwrap());
        let geom = if length(&left) > 0.0 && length(&right) > 0.0 {
            let mut ring: Vec<_> = left.0.clone();
            ring.extend(right.0.iter().rev().copied());
            let shape = Mp::new(vec![geo::Polygon::new(LineString::new(ring), vec![])]);
            ops::snap(&ops::intersection(&ops::orient(&shape), area), GRID_M)
        } else {
            Mp::new(vec![])
        };
        let a = w0[i].unwrap_or(0.0);
        let b = w1[i].or(w0[i]).unwrap_or(0.0);
        lanes.push(d::Lane {
            id: l,
            cid: c,
            n: num[i].unwrap_or(0),
            role: role[i].clone().unwrap_or_default(),
            turn: turn[i].clone(),
            w: round2((a + b) / 2.0),
            method: method[i].clone().unwrap_or_default(),
            srcs: srcs[i].clone().unwrap_or_default(),
            left,
            right,
            geom,
        });
    }

    // ---- the junctions: a street carriageway runs inside one or ends at one
    let jc = open("junction-cut.parquet")?;
    let ja = open("junction-area.parquet")?;
    let (aj, aarea) = (ja.i64s("junction_id"), blobs(&ja, "area"));
    let mut area_of: BTreeMap<i64, usize> = BTreeMap::new();
    for i in rows(&ja, "junction_area") {
        if let Some(j) = aj[i] {
            area_of.insert(j, i);
        }
    }
    let inside_ids: BTreeSet<i64> = carriageways.iter().filter_map(|c| c.inside).collect();
    let (jid, nodes, kind, control, jlevel, jmethod) = (
        jc.i64s("junction_id"),
        jc.list_i64s("node_ids"),
        jc.strs("kind"),
        jc.strs("control"),
        jc.i64s("level"),
        jc.strs("ev_method"),
    );
    let mut junctions = Vec::new();
    for i in rows(&jc, "junction") {
        let Some(j) = jid[i] else { continue };
        let Some(&a) = area_of.get(&j) else { continue };
        let Some(wkb::Geom::Polys(m)) = aarea[a].as_ref().map(clone_geom) else { continue };
        let ns = nodes[i].clone().unwrap_or_default();
        if !reaches_mp(area, &m) || !(inside_ids.contains(&j) || ns.iter().any(|n| ends.contains(n))) {
            continue;
        }
        junctions.push(d::Junction { id: j, nodes: ns, kind: kind[i].clone().unwrap_or_default(), control: control[i].clone(), level: level_of(jlevel[i]), method: jmethod[i].clone().unwrap_or_default(), area: m });
    }

    // ---- the islands, the stop lines
    let (ij, ik, il, im) = (ja.i64s("junction_id"), ja.strs("kind"), ja.i64s("level"), ja.strs("ev_method"));
    let mut islands = Vec::new();
    for i in rows(&ja, "island") {
        let Some(wkb::Geom::Polys(m)) = aarea[i].as_ref().map(clone_geom) else { continue };
        if reaches_mp(area, &m) {
            islands.push(d::Island { j: ij[i], kind: ik[i].clone().unwrap_or_default(), level: level_of(il[i]), method: im[i].clone().unwrap_or_default(), geom: m });
        }
    }
    let (sc, sj, sm, sg) = (jc.i64s("carriageway_id"), jc.i64s("junction_id"), jc.strs("method"), blobs(&jc, "geometry"));
    let mut stops = Vec::new();
    for i in rows(&jc, "stop_line") {
        let (Some(c), Some(wkb::Geom::Lines(l))) = (sc[i], sg[i].as_ref().map(clone_geom)) else { continue };
        if reaches_lines(area, &l) {
            stops.push(d::Stop { cid: c, j: sj[i], method: sm[i].clone().unwrap_or_default(), lines: l });
        }
    }

    // ---- the moves, the faces of the other levels
    let mv = open("connectors.parquet")?;
    let (mj, mfl, mtl, mfc, mtc, mturn, muses, mmethod, mpath) = (
        mv.i64s("junction_id"),
        mv.i64s("from_lane_id"),
        mv.i64s("to_lane_id"),
        mv.i64s("from_carriageway_id"),
        mv.i64s("to_carriageway_id"),
        mv.strs("turn"),
        mv.list_strs("allowed_uses"),
        mv.strs("ev_method"),
        blobs(&mv, "path"),
    );
    let mut moves = Vec::new();
    for i in rows(&mv, "movement") {
        let (Some(j), Some(fl), Some(tl), Some(fc), Some(tc), Some(wkb::Geom::Lines(l))) = (mj[i], mfl[i], mtl[i], mfc[i], mtc[i], mpath[i].as_ref().map(clone_geom)) else { continue };
        if reaches_lines(area, &l) {
            moves.push(d::Move { j, fl, tl, fc, tc, turn: mturn[i].clone().unwrap_or_default(), uses: muses[i].clone().unwrap_or_default(), method: mmethod[i].clone().unwrap_or_default(), lines: l });
        }
    }
    let ss = open("street-space.parquet")?;
    let (fl, fg) = (ss.i64s("level"), blobs(&ss, "geometry"));
    let mut faces = Vec::new();
    for i in rows(&ss, "street_face") {
        if fl[i].unwrap_or(0) == 0 {
            continue;
        }
        let Some(wkb::Geom::Polys(m)) = fg[i].as_ref().map(clone_geom) else { continue };
        if reaches_mp(area, &m) {
            faces.push(d::Face { level: level_of(fl[i]), geom: m });
        }
    }
    Ok(Sim { carriageways, lanes, junctions, islands, stops, moves, faces })
}

fn length(l: &LineString<f64>) -> f64 {
    use geo::{Euclidean, Length};
    Euclidean.length(l)
}

fn clone_geom(g: &wkb::Geom) -> wkb::Geom {
    match g {
        wkb::Geom::Point(c) => wkb::Geom::Point(*c),
        wkb::Geom::Lines(l) => wkb::Geom::Lines(l.clone()),
        wkb::Geom::Polys(p) => wkb::Geom::Polys(p.clone()),
    }
}
