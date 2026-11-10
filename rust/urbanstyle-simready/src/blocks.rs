//! The street inputs of the blocks step from SimReady's Parquet files (what `simready.read` gives `sr_blocks.build`): SimReady's ground
//! face and its roundabouts' faces at level 0, the lanes of the street carriageways, the lanes of the drives (the carriageways that are no
//! street), the junction areas of the streets, and one line for each street carriageway with its OSM way, name and class.
use crate::division::{is_street, Edges};
use crate::{table::Table, wkb};
use geo::{BoundingRect, Intersects, LineString, Polygon};
use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;
use urbanstyle_blocks::Street;
use urbanstyle_geo::ops::{self, Mp};

pub struct BlocksSim {
    pub face: Mp,
    pub lanes: Vec<Mp>,
    pub drives: Vec<Mp>,
    pub junctions: Vec<Mp>,
    pub streets: Vec<Street>,
}

pub fn read(dir: &Path, edges: &Edges, area: &Mp) -> Result<BlocksSim, String> {
    let rows = |t: &Table, kind: &str| -> Vec<usize> { t.strs("table").iter().enumerate().filter(|(_, k)| k.as_deref() == Some(kind)).map(|(i, _)| i).collect() };
    let geoms = |t: &Table, col: &str| -> Vec<Option<wkb::Geom>> { t.blobs(col).into_iter().map(|b| b.and_then(|b| wkb::parse(&b))).collect() };

    // ---- the carriageways at level 0 that reach into the area
    let t = Table::open(&dir.join("reference-line.parquet"))?;
    let (id, eids, hw, name, inside, level, from, to) = (
        t.i64s("carriageway_id"),
        t.list_i64s("edge_ids"),
        t.strs("highway"),
        t.strs("name"),
        t.i64s("inside_junction_id"),
        t.i64s("level"),
        t.i64s("from_node_id"),
        t.i64s("to_node_id"),
    );
    let lines = geoms(&t, "reference_line");
    struct Cw {
        street: bool,
        way: Option<i64>,
        name: Option<String>,
        class: String,
        inside: Option<i64>,
        line: LineString<f64>,
    }
    let mut cws: BTreeMap<i64, Cw> = BTreeMap::new();
    let mut ends: BTreeSet<i64> = BTreeSet::new();
    for i in rows(&t, "carriageway") {
        let (Some(c), Some(wkb::Geom::Lines(l))) = (id[i], lines[i].as_ref()) else { continue };
        if level[i].unwrap_or(0) != 0 || l.len() != 1 || !(l[0].bounding_rect().is_some() && area.intersects(&l[0])) {
            continue;
        }
        let es: Vec<i64> = eids[i].clone().unwrap_or_default().into_iter().filter(|e| edges.way.contains_key(e)).collect();
        let h = hw[i].clone().unwrap_or_default();
        let street = is_street(&h, name[i].as_deref(), &eids[i].clone().unwrap_or_default(), &edges.service);
        // the way of the longest of its edges (the first of equal ones)
        let mut best: Option<(i64, f64)> = None;
        for e in es.iter().filter_map(|e| edges.way.get(e)) {
            if best.map_or(true, |b| e.1 > b.1) {
                best = Some(*e);
            }
        }
        if street {
            ends.extend(from[i]);
            ends.extend(to[i]);
        }
        cws.insert(c, Cw { street, way: best.map(|b| b.0), name: name[i].clone(), class: h, inside: inside[i], line: l[0].clone() });
    }

    // ---- the lanes: the polygon between the two boundaries of each lane
    let lb = Table::open(&dir.join("lane-boundaries.parquet"))?;
    let wp = Table::open(&dir.join("width-profiles.parquet"))?;
    let (lid, bl, br) = (lb.i64s("lane_id"), geoms(&lb, "boundary_left"), geoms(&lb, "boundary_right"));
    let bounds: BTreeMap<i64, usize> = lid.iter().enumerate().filter_map(|(k, l)| l.map(|l| (l, k))).collect();
    let (lane_id, lane_cw) = (wp.i64s("lane_id"), wp.i64s("carriageway_id"));
    let (mut lanes, mut drives) = (Vec::new(), Vec::new());
    for i in rows(&wp, "lane") {
        let (Some(l), Some(c)) = (lane_id[i], lane_cw[i]) else { continue };
        let Some(cw) = cws.get(&c) else { continue };
        let Some(&k) = bounds.get(&l) else { continue };
        let (Some(wkb::Geom::Lines(left)), Some(wkb::Geom::Lines(right))) = (bl[k].as_ref(), br[k].as_ref()) else { continue };
        // (a lane with a boundary of no length has no shape: the Python reader skips it)
        let len = |l: &LineString<f64>| geo::Length::length(&geo::Euclidean, l);
        if left.len() != 1 || right.len() != 1 || len(&left[0]) <= 0.0 || len(&right[0]) <= 0.0 {
            continue;
        }
        let mut ring = left[0].0.clone();
        ring.extend(right[0].0.iter().rev().copied());
        let shape = ops::orient(&Mp::new(vec![Polygon::new(LineString::new(ring), vec![])]));
        if cw.street { lanes.push(shape) } else { drives.push(shape) }
    }

    // ---- the junction areas of the streets: a street carriageway runs inside one or ends at one
    let jc = Table::open(&dir.join("junction-cut.parquet"))?;
    let ja = Table::open(&dir.join("junction-area.parquet"))?;
    let (aj, aarea) = (ja.i64s("junction_id"), geoms(&ja, "area"));
    let area_of: BTreeMap<i64, usize> = rows(&ja, "junction_area").into_iter().filter_map(|i| aj[i].map(|j| (j, i))).collect();
    let inside_ids: BTreeSet<i64> = cws.values().filter(|c| c.street).filter_map(|c| c.inside).collect();
    let (jid, nodes, jlevel) = (jc.i64s("junction_id"), jc.list_i64s("node_ids"), jc.i64s("level"));
    let mut junctions = Vec::new();
    for i in rows(&jc, "junction") {
        let Some(j) = jid[i] else { continue };
        let Some(&a) = area_of.get(&j) else { continue };
        let Some(wkb::Geom::Polys(m)) = aarea[a].as_ref() else { continue };
        let ns = nodes[i].clone().unwrap_or_default();
        if jlevel[i].unwrap_or(0) != 0 || !(m.bounding_rect().is_some() && area.intersects(m)) || !(inside_ids.contains(&j) || ns.iter().any(|n| ends.contains(n))) {
            continue;
        }
        junctions.push(m.clone());
    }

    // ---- the face: the ground face and the roundabouts' faces at level 0, in the area
    let ss = Table::open(&dir.join("street-space.parquet"))?;
    let (kind, fl, fg) = (ss.strs("kind"), ss.i64s("level"), geoms(&ss, "geometry"));
    let mut faces = Vec::new();
    for i in rows(&ss, "street_face") {
        if fl[i].unwrap_or(0) != 0 || !matches!(kind[i].as_deref(), Some("ground") | Some("roundabout")) {
            continue;
        }
        if let Some(wkb::Geom::Polys(m)) = fg[i].as_ref() {
            faces.push(ops::orient(m));
        }
    }
    let face = ops::intersection(&ops::union_all(faces.iter()), area);

    let streets = cws.values().filter(|c| c.street).filter_map(|c| c.way.map(|w| Street { way: w, name: c.name.clone(), class: c.class.clone(), line: c.line.clone() })).collect();
    Ok(BlocksSim { face, lanes, drives, junctions, streets })
}
