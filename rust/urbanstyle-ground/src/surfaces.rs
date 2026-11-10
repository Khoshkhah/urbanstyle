//! Layer 1 of the ground (docs/design/space-layers.md): every ground item is covered by its surfaces, one row per piece of each kind in it.
//! The port of `ground.surfaces`: in a street the roadway, the median, the pedestrian realm (from its parts) and a verge; in a plot its
//! buildings, car park, construction site, garden (OSM) and the yard (the rest); in green play land, paths and the lawn; for the other
//! kinds the item itself. What no source names joins the surface it shares the most edge with.
use crate::MIN_M2;
use geo::{Area, BoundingRect, Centroid, LineString, Polygon};
use std::collections::BTreeMap;
use urbanstyle_geo::index::{Index, NearIndex};
use urbanstyle_geo::ops::{self, Mp};

/// A piece of a surface smaller than this is a hairline.
const HAIRLINE_M2: f64 = 0.01;
/// A path is the walkway line widened by this to each side.
const PATH_HALF_M: f64 = 1.0;
const NEAR_M: f64 = 0.05;

/// The surface of a street part, from its type.
pub fn street_surface(typ: &str) -> Option<&'static str> {
    Some(match typ {
        "lane" | "bus lane" | "cycle lane" | "paved" | "junction area" | "ring" | "shoulder" | "parking" | "no parking" | "bus zone" | "crosswalk" | "cycle crossing" => "roadway",
        "sidewalk" | "furnishing" | "frontage" | "open" | "bus stop" | "tree pit" | "driveway" => "pedestrian realm",
        "island" | "barrier" => "median",
        _ => return None,
    })
}

/// The surface of a ground item that is one surface.
fn one_surface(typ: &str) -> &str {
    match typ {
        "alley" => "roadway",
        "rail" => "track bed",
        "structure" => "under bridge",
        "square" => "paved",
        t => t,
    }
}

#[derive(Clone)]
pub struct GroundItem {
    pub id: String,
    pub typ: String,
    pub r#ref: Option<String>,
    pub source: Option<String>,
    pub method: Option<String>,
    pub geom: Mp,
}

#[derive(Clone)]
pub struct StreetPart {
    pub unit: String,
    pub typ: String,
    pub source: Option<String>,
    pub geom: Mp,
}

/// An OSM layer: items with an id and an outline.
#[derive(Clone, Default)]
pub struct Layer {
    pub items: Vec<(String, Mp)>,
}

#[derive(Clone, Default)]
pub struct Layers {
    pub verge: Layer,
    pub garden: Layer,
    pub play: Layer,
    pub buildings: Layer,
    pub lots: Layer,
    pub sites: Layer,
    /// Walkways and cycleways (their lines; widened by `PATH_HALF_M` here).
    pub walks: Vec<(String, Vec<LineString<f64>>)>,
}

#[derive(Clone)]
pub struct SurfaceInput {
    pub ground: Vec<GroundItem>,
    pub parts: Vec<StreetPart>,
    pub layers: Layers,
}

pub struct Surface {
    pub id: String,
    pub ground: String,
    pub kind: String,
    pub source: String,
    pub method: String,
    pub r#ref: Option<String>,
    pub geom: Polygon<f64>,
}

struct Indexed {
    items: Vec<(String, Mp)>,
    index: Index,
}

impl Indexed {
    fn new(items: Vec<(String, Mp)>) -> Self {
        let index = Index::new(items.iter().map(|(_, m)| m.bounding_rect()));
        Indexed { items, index }
    }

    /// The items whose box meets the box of `g`, joined, and their ids (`inside` of the Python code: no test of the shapes).
    fn hits(&self, g: &Mp) -> Option<(Mp, String)> {
        let r = g.bounding_rect()?;
        let mut ks = self.index.query(&r);
        ks.sort();
        if ks.is_empty() {
            return None;
        }
        Some((ops::union_all(ks.iter().map(|&k| &self.items[k].1)), ks.iter().map(|&k| self.items[k].0.clone()).collect::<Vec<_>>().join(", ")))
    }
}

fn layer(l: &Layer) -> Indexed {
    Indexed::new(l.items.iter().map(|(r, g)| (r.clone(), ops::orient(g))).collect())
}

/// Python's `round(x, 1)`.
fn r1(x: f64) -> i64 {
    (x * 10.0).round_ties_even() as i64
}

pub fn build(inp: &SurfaceInput) -> Vec<Surface> {
    // the parts of each street space by surface, and their sources
    let mut parts: BTreeMap<&str, BTreeMap<&'static str, Vec<Mp>>> = BTreeMap::new();
    let mut psrc: BTreeMap<(&str, &'static str), std::collections::BTreeSet<String>> = BTreeMap::new();
    for p in &inp.parts {
        if let Some(s) = street_surface(&p.typ) {
            parts.entry(p.unit.as_str()).or_default().entry(s).or_default().push(ops::orient(&p.geom));
            let set = psrc.entry((p.unit.as_str(), s)).or_default();
            for x in p.source.as_deref().unwrap_or("urbanstyle").split('+') {
                set.insert(x.to_string());
            }
        }
    }
    let (verge, garden, play) = (layer(&inp.layers.verge), layer(&inp.layers.garden), layer(&inp.layers.play));
    let (blds, lots, sites) = (layer(&inp.layers.buildings), layer(&inp.layers.lots), layer(&inp.layers.sites));
    let walks = Indexed::new(
        inp.layers
            .walks
            .iter()
            .map(|(r, ls)| (r.clone(), ops::union_all(ls.iter().map(|l| ops::buffer_line(l, PATH_HALF_M)).collect::<Vec<_>>().iter())))
            .collect(),
    );

    let mut out = Vec::new();
    for gi in &inp.ground {
        let g = ops::orient(&gi.geom);
        // (kind, geometry, source, method, refs), in the order they take the ground
        let mut claims: Vec<(String, Mp, String, String, Option<String>)> = Vec::new();
        let hit = |ix: &Indexed, kind: &str, claims: &mut Vec<(String, Mp, String, String, Option<String>)>| {
            if let Some((m, refs)) = ix.hits(&g) {
                claims.push((kind.to_string(), m, "osm".into(), "mapped".into(), Some(refs)));
            }
        };
        match gi.typ.as_str() {
            "street" => {
                let unit = gi.r#ref.as_deref().unwrap_or("");
                for kind in ["roadway", "median", "pedestrian realm"] {
                    if let Some(v) = parts.get(unit).and_then(|m| m.get(kind)) {
                        let src = psrc[&(unit, kind)].iter().cloned().collect::<Vec<_>>().join("+");
                        claims.push((kind.to_string(), ops::union_all(v.iter()), src, "derived".into(), Some(format!("the parts of {unit}"))));
                    }
                }
                if claims.is_empty() {
                    // a piece of right-of-way a road runs through (a back lane in a block), no space's parts in it
                    claims.push(("roadway".into(), g.clone(), "osm".into(), "mapped".into(), gi.r#ref.clone()));
                }
                if let Some((m, refs)) = verge.hits(&g) {
                    // a verge takes the pedestrian realm's ground where OSM maps grass, never the roadway's
                    let at = claims.len().min(2);
                    claims.insert(at, ("verge".into(), m, "osm".into(), "mapped".into(), Some(refs)));
                }
            }
            "plot" => {
                hit(&blds, "building", &mut claims);
                hit(&lots, "car park", &mut claims);
                hit(&sites, "construction site", &mut claims);
                hit(&garden, "garden", &mut claims);
                claims.push(("yard".into(), g.clone(), "urbanstyle".into(), "derived".into(), None));
            }
            "yard" => {
                hit(&garden, "garden", &mut claims);
                claims.push(("yard".into(), g.clone(), "urbanstyle".into(), "derived".into(), None));
            }
            "green" => {
                hit(&play, "play", &mut claims);
                hit(&walks, "path", &mut claims);
                claims.push(("lawn".into(), g.clone(), "urbanstyle".into(), "derived".into(), None));
            }
            t => claims.push((one_surface(t).to_string(), g.clone(), gi.source.clone().unwrap_or_else(|| "urbanstyle".into()), gi.method.clone().unwrap_or_else(|| "derived".into()), gi.r#ref.clone())),
        }
        // each claim takes what the earlier ones left
        let mut taken: Vec<Mp> = Vec::new();
        let mut mine: Vec<(String, String, String, String, Option<String>, Mp)> = Vec::new();
        for (kind, geom, s, me, r) in claims {
            let mut piece = ops::intersection(&geom, &g);
            if !taken.is_empty() {
                piece = ops::difference(&piece, &ops::union_all(taken.iter()));
            }
            if ops::area(&piece) < MIN_M2 {
                continue;
            }
            taken.push(piece.clone());
            mine.push((format!("{}:{kind}", gi.id), kind, s, me, r, piece));
        }
        if !mine.is_empty() {
            // what no source names joins its neighbour in this item
            // (the pieces are disjoint and inside the item, so when their areas fill it, what is left is below the hairline: no difference needed)
            let rest = if ops::area(&g) - taken.iter().map(ops::area).sum::<f64>() < HAIRLINE_M2 { Mp::new(vec![]) } else { ops::difference(&g, &ops::union_all(taken.iter())) };
            // (one index of every claim's rings, and one union for each claim that gets pieces: a union of the whole claim for each small
            // piece was most of the time of this step)
            let small: Vec<&Polygon<f64>> = rest.0.iter().filter(|p| p.unsigned_area() >= HAIRLINE_M2).collect();
            if !small.is_empty() {
                let near = NearIndex::tagged(mine.iter().enumerate().flat_map(|(i, m)| m.5 .0.iter().flat_map(|q| std::iter::once(q.exterior()).chain(q.interiors())).map(move |r| (i, r))));
                let mut add: BTreeMap<usize, Vec<Mp>> = BTreeMap::new();
                for p in small {
                    let lens = near.covered_by_tag(std::iter::once(p.exterior()).chain(p.interiors()), NEAR_M);
                    // (the first claim with the most shared edge; the first claim where none shares any)
                    let i = lens.into_iter().fold(None::<(usize, f64)>, |b, c| match b {
                        Some(x) if x.1 >= c.1 => Some(x),
                        _ => Some(c),
                    });
                    add.entry(i.map_or(0, |x| x.0)).or_default().push(Mp::new(vec![p.clone()]));
                }
                for (i, ps) in add {
                    let mut parts = vec![mine[i].5.clone()];
                    parts.extend(ps);
                    mine[i].5 = ops::union_all(parts.iter());
                }
            }
        }
        // one item per piece: the sidewalk on each side, each building
        for (id, kind, s, me, r, geom) in mine {
            let mut ps: Vec<Polygon<f64>> = geom.0.into_iter().filter(|p| p.unsigned_area() >= HAIRLINE_M2).collect();
            ps.sort_by_key(|p| p.centroid().map_or((0, 0), |c| (r1(c.x()), r1(c.y()))));
            let single = ps.len() == 1;
            for (n, p) in ps.into_iter().enumerate() {
                out.push(Surface { id: if single { id.clone() } else { format!("{id}/{}", n + 1) }, ground: gi.id.clone(), kind: kind.clone(), source: s.clone(), method: me.clone(), r#ref: r.clone(), geom: p });
            }
        }
    }
    out
}
