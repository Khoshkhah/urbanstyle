//! Rank 1 of the model: the street (its connected pieces), the plots (the blocks) and the paths (the corridors), and the pieces of the
//! plots (`product.write`, "rank 1").
use crate::Input;
use geo::{BoundingRect, Distance, Euclidean, InteriorPoint, Polygon};
use std::collections::BTreeMap;
use urbanstyle_geo::index::{Index, SegIndex};
use urbanstyle_geo::ops::{self, Mp};

/// An alley's width where OSM gives none (chosen; `ground.ALLEY_W_M`).
pub const ALLEY_W_M: f64 = 6.0;

pub struct GroundRow {
    pub id: String,
    pub kind: String,
    pub parent: String,
    pub level: i32,
    pub name: Option<String>,
    pub sides: Option<Vec<crate::BlockSideIn>>,
    pub width_m: Option<f64>,
    pub width_source: Option<String>,
    pub width_method: Option<String>,
    pub source: Option<String>,
    pub method: Option<String>,
    pub r#ref: Option<String>,
    pub geom: Mp,
}

pub struct PlotPieceRow {
    pub id: String,
    pub kind: String,
    pub parent: Option<String>,
    pub level: i32,
    pub name: Option<String>,
    pub width_m: Option<f64>,
    pub width_source: Option<String>,
    pub width_method: Option<String>,
    pub surfaces: Vec<String>,
    pub source: Option<String>,
    pub method: Option<String>,
    pub r#ref: Option<String>,
    pub geom: Mp,
}

/// Candidates (an id and an outline) to name the parent of a child: the one that holds its inner point (the smallest if several), else
/// the one that overlaps it most (`product.write.best`).
pub struct Best {
    items: Vec<(String, Mp)>,
    index: Index,
    segs: Vec<SegIndex>,
}

impl Best {
    pub fn new(items: Vec<(String, Mp)>) -> Self {
        let index = Index::new(items.iter().map(|(_, m)| m.bounding_rect()));
        let segs = items.iter().map(|(_, m)| SegIndex::new(m)).collect();
        Best { items, index, segs }
    }

    pub fn of(&self, child: &Mp) -> Option<String> {
        let r = child.bounding_rect()?;
        let pt = child.interior_point()?;
        let near = self.index.query(&r);
        let inside = near.iter().copied().filter(|&k| self.segs[k].contains(pt.0)).min_by(|&a, &b| ops::area(&self.items[a].1).partial_cmp(&ops::area(&self.items[b].1)).unwrap());
        if let Some(k) = inside {
            return Some(self.items[k].0.clone());
        }
        // (the candidates that meet the child, a shared edge too; the one with the largest overlap, the first of equals)
        let mut best: Option<(usize, f64)> = None;
        for k in near {
            // (the full distance compares every edge with every edge: only a pair with edges near each other, or one inside the other,
            // can be nearer than 1e-9 m, so the others are passed over first)
            let near_edges = child.0.iter().flat_map(|p| std::iter::once(p.exterior()).chain(p.interiors())).flat_map(|r| r.lines()).any(|l| {
                let (lo, hi) = (geo::Coord { x: l.start.x.min(l.end.x) - 1e-6, y: l.start.y.min(l.end.y) - 1e-6 }, geo::Coord { x: l.start.x.max(l.end.x) + 1e-6, y: l.start.y.max(l.end.y) + 1e-6 });
                !self.segs[k].edges_in(&geo::Rect::new(lo, hi)).is_empty()
            });
            let one_in_other = || {
                let item_pt = self.items[k].1.0.first().and_then(|p| p.exterior().0.first().copied());
                let child_pt = child.0.first().and_then(|p| p.exterior().0.first().copied());
                child_pt.map_or(false, |c| self.segs[k].contains(c)) || item_pt.map_or(false, |c| geo::Contains::contains(child, &geo::Point::from(c)))
            };
            if !near_edges && !one_in_other() {
                continue;
            }
            if Euclidean.distance(&self.items[k].1, child) > 1e-9 {
                continue;
            }
            let a = ops::area(&ops::intersection(&self.items[k].1, child));
            if best.map_or(true, |b| a > b.1) {
                best = Some((k, a));
            }
        }
        best.map(|x| self.items[x.0].0.clone())
    }
}

fn polygons_by_area(m: &Mp) -> Vec<Polygon<f64>> {
    let mut v: Vec<Polygon<f64>> = m.0.clone();
    v.sort_by(|a, b| geo::Area::unsigned_area(b).partial_cmp(&geo::Area::unsigned_area(a)).unwrap());
    v
}

/// The street pieces of each level, the plots, the paths: the rows of `urban.ground`, and the pieces of the plots.
pub fn build(inp: &Input, levels: &[i32]) -> (Vec<GroundRow>, Vec<PlotPieceRow>, BTreeMap<i32, Best>) {
    // (the street's best is returned: the stretches name their parent among the street pieces)
    let mut lap = urbanstyle_geo::Lap::new("model rank 1");
    let mut rows: Vec<GroundRow> = Vec::new();
    let mut street_pieces: BTreeMap<i32, Vec<(String, Mp)>> = BTreeMap::new();
    for &lv in levels {
        let from_ground: Vec<&Mp> = inp.ground.iter().filter(|x| x.level == lv && x.typ == "street").map(|x| &x.geom).collect();
        let from_rows = !from_ground.is_empty();
        let pieces: Vec<&Mp> = if from_ground.is_empty() { inp.units.iter().filter(|u| u.level == lv).map(|u| &u.geom).collect() } else { from_ground };
        // (the spaces are cut by separate overlays: where two meet, their edges can be a few millimetres apart; the union is closed by 1 cm)
        let polys = if pieces.is_empty() {
            vec![]
        } else {
            let u = ops::union_all(pieces.into_iter());
            let h = inp.close_gaps_m / 2.0;
            polygons_by_area(&if from_rows && h > 0.0 { ops::buffer_mitre(&ops::buffer_mitre(&u, h), -h) } else { u })
        };
        let list: Vec<(String, Mp)> = polys.into_iter().enumerate().map(|(n, p)| (format!("g{lv}-street-{}", n + 1), Mp::new(vec![p]))).collect();
        for (id, g) in &list {
            rows.push(GroundRow {
                id: id.clone(),
                kind: "street".into(),
                parent: format!("a{lv}"),
                level: lv,
                name: None,
                sides: None,
                width_m: None,
                width_source: None,
                width_method: None,
                source: Some("urbanstyle".into()),
                method: Some("derived".into()),
                r#ref: Some(if lv == 0 { "the area less the blocks and the corridors" } else { "the spaces of the level" }.into()),
                geom: g.clone(),
            });
        }
        street_pieces.insert(lv, list);
    }
    lap.lap("street pieces");
    let mut sides: BTreeMap<&str, Vec<crate::BlockSideIn>> = BTreeMap::new();
    for s in &inp.block_sides {
        sides.entry(s.block.as_str()).or_default().push(s.clone());
    }
    let mut plots: BTreeMap<i32, Vec<(String, Mp)>> = BTreeMap::new();
    for b in &inp.blocks {
        let pid = format!("g{}-plot-{}", b.level, b.id);
        plots.entry(b.level).or_default().push((pid.clone(), b.geom.clone()));
        rows.push(GroundRow {
            id: pid,
            kind: "plot".into(),
            parent: format!("a{}", b.level),
            level: b.level,
            name: None,
            sides: sides.get(b.id.as_str()).cloned(),
            width_m: None,
            width_source: None,
            width_method: None,
            source: Some(b.source.clone().unwrap_or_else(|| "urbanstyle".into())),
            method: Some(b.method.clone().unwrap_or_else(|| "derived".into())),
            r#ref: Some(b.id.clone()),
            geom: b.geom.clone(),
        });
    }
    let corr: BTreeMap<&str, &crate::CorridorIn> = inp.corridors.iter().map(|c| (c.id.as_str(), c)).collect();
    for x in inp.ground.iter().filter(|x| x.typ == "path") {
        let c = x.r#ref.as_deref().and_then(|r| corr.get(r));
        rows.push(GroundRow {
            id: x.id.clone(),
            kind: "path".into(),
            parent: format!("a{}", x.level),
            level: x.level,
            name: c.map_or(x.name.clone(), |c| c.name.clone()),
            sides: None,
            width_m: c.and_then(|c| c.width),
            width_source: c.and_then(|c| c.source.clone()),
            width_method: c.and_then(|c| c.method.clone()),
            source: x.source.clone(),
            method: x.method.clone(),
            r#ref: x.r#ref.clone(),
            geom: x.geom.clone(),
        });
    }

    lap.lap("plots and paths");
    // ---- the pieces of the plots: every ground item that is no street and no path
    let plot_best: BTreeMap<i32, Best> = plots.into_iter().map(|(lv, v)| (lv, Best::new(v))).collect();
    let mut surf_of: BTreeMap<&str, Vec<String>> = BTreeMap::new();
    for s in &inp.surfaces {
        surf_of.entry(s.ground.as_str()).or_default().push(s.id.clone());
    }
    let way_of = |s: &str| -> Option<String> {
        // (the first `w` and digits in the text)
        let b = s.as_bytes();
        (0..b.len()).find(|&i| b[i] == b'w' && b.get(i + 1).map_or(false, |c| c.is_ascii_digit())).map(|i| {
            let end = (i + 1..b.len()).find(|&j| !b[j].is_ascii_digit()).unwrap_or(b.len());
            s[i..end].to_string()
        })
    };
    let mut pieces = Vec::new();
    for x in inp.ground.iter().filter(|x| x.typ != "street" && x.typ != "path") {
        let (mut wd, mut ws, mut wm) = (None, None, None);
        if x.typ == "alley" {
            let way = way_of(x.r#ref.as_deref().unwrap_or(&x.id));
            match way.and_then(|w| inp.owidth.get(&w).copied()) {
                Some(w) => (wd, ws, wm) = (Some(w), Some("osm".to_string()), Some("mapped".to_string())),
                None => (wd, ws, wm) = (Some(ALLEY_W_M), Some("urbanstyle".to_string()), Some("chosen".to_string())),
            }
        }
        let mut surfaces = surf_of.get(x.id.as_str()).cloned().unwrap_or_default();
        surfaces.sort();
        pieces.push(PlotPieceRow {
            id: x.id.clone(),
            kind: x.typ.clone(),
            parent: plot_best.get(&x.level).and_then(|b| b.of(&x.geom)),
            level: x.level,
            name: x.name.clone(),
            width_m: wd,
            width_source: ws,
            width_method: wm,
            surfaces,
            source: x.source.clone(),
            method: x.method.clone(),
            r#ref: x.r#ref.clone(),
            geom: x.geom.clone(),
        });
    }
    lap.lap("plot pieces");
    let street_best: BTreeMap<i32, Best> = street_pieces.into_iter().map(|(lv, v)| (lv, Best::new(v))).collect();
    lap.lap("street best");
    (rows, pieces, street_best)
}
