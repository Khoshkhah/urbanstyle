//! The street of each road, as the Python `container.street_owner` groups them (the "old SQL" pipeline whose `work.arm` and `work.street`
//! the model step reads): a street is the road edges of one level that share a name and are joined at a shared node (an unnamed road is
//! its own way), with the two halves of a dual carriageway joined when their chains end at the same intersections. Its id is
//! `k<level>-<smallest OSM way id>`. Only the roads are grouped here: footpaths and rails make path and rail spaces, not streets.
use crate::osm::{DrivingEdge, Way};
use geo::{BoundingRect, Distance, Euclidean, Length, LineString};
use std::collections::{BTreeMap, BTreeSet, HashMap};
use urbanstyle_geo::index::{Index, NearIndex};

const DUAL_CARRIAGEWAY_M: f64 = 40.0;
const DUAL_ALONGSIDE: f64 = 0.6;
const DUAL_ANTIPARALLEL_DEG: f64 = 135.0;
const MERGE_NODES_M: f64 = 15.0;
const MERGE_DIAMETER_M: f64 = 30.0;
/// The levels the build keeps (`container.LEVELS`).
const LEVELS: (i64, i64) = (-2, 2);

struct Uf(Vec<usize>);

impl Uf {
    fn new(n: usize) -> Uf {
        Uf((0..n).collect())
    }
    fn find(&mut self, x: usize) -> usize {
        let mut r = x;
        while self.0[r] != r {
            r = self.0[r];
        }
        let mut x = x;
        while self.0[x] != r {
            let n = self.0[x];
            self.0[x] = r;
            x = n;
        }
        r
    }
    fn union(&mut self, a: usize, b: usize) {
        let (a, b) = (self.find(a), self.find(b));
        if a != b {
            self.0[a] = b;
        }
    }
}

struct Road<'a> {
    level: i64,
    osm_id: i64,
    name: Option<&'a str>,
    src: i64,
    dst: i64,
    oneway: bool,
    line: &'a LineString<f64>,
}

pub struct Streets {
    /// `w<osm id>` to the street of the way, for the ways that arrive at a junction node (the rows of `work.arm`).
    pub way_street: BTreeMap<String, String>,
    /// (name, level) to the street that has the name.
    pub name_street: BTreeMap<(String, i32), String>,
}

/// The nodes of each junction cluster: junction nodes closer than `MERGE_NODES_M` form one, as do those of one roundabout and the pairs
/// of a dual carriageway, while the cluster stays under `MERGE_DIAMETER_M` across (`container.junction_clusters`).
fn clusters(nodes: &[(i64, i64, f64, f64)], rings: &[BTreeSet<i64>], extra: &[(i64, i64, i64)]) -> HashMap<(i64, i64), (i64, usize)> {
    let mut out = HashMap::new();
    let levels: BTreeSet<i64> = nodes.iter().map(|n| n.0).collect();
    for level in levels {
        let ns: Vec<&(i64, i64, f64, f64)> = nodes.iter().filter(|n| n.0 == level).collect();
        let idx_of: HashMap<i64, usize> = ns.iter().enumerate().map(|(i, n)| (n.1, i)).collect();
        let mut uf = Uf::new(ns.len());
        let mut ring_idx: BTreeSet<usize> = BTreeSet::new();
        for ring in rings {
            let on: Vec<usize> = ring.iter().filter_map(|n| idx_of.get(n).copied()).collect();
            for &i in on.iter().skip(1) {
                uf.union(i, on[0]);
            }
            if on.len() >= 2 {
                ring_idx.extend(on);
            }
        }
        for &(lv, u, v) in extra {
            if lv == level {
                if let (Some(&a), Some(&b)) = (idx_of.get(&u), idx_of.get(&v)) {
                    uf.union(a, b);
                }
            }
        }
        let mut members: BTreeMap<usize, Vec<usize>> = BTreeMap::new();
        for i in 0..ns.len() {
            let r = uf.find(i);
            members.entry(r).or_default().push(i);
        }
        let mut forced: BTreeSet<usize> = members.iter().filter(|(r, m)| m.len() > 1 || ring_idx.contains(r)).map(|(r, _)| *r).collect();
        let d = |a: usize, b: usize| (ns[a].2 - ns[b].2).hypot(ns[a].3 - ns[b].3);
        // (the others: closest pairs first, while the merged cluster stays under the diameter)
        let mut pairs: Vec<(f64, usize, usize)> = Vec::new();
        for a in 0..ns.len() {
            for b in a + 1..ns.len() {
                let dist = d(a, b);
                if dist <= MERGE_NODES_M {
                    pairs.push((dist, a, b));
                }
            }
        }
        pairs.sort_by(|x, y| x.partial_cmp(y).unwrap());
        for (_, a, b) in pairs {
            let (ra, rb) = (uf.find(a), uf.find(b));
            if ra == rb {
                continue;
            }
            let both: Vec<usize> = members[&ra].iter().chain(members[&rb].iter()).copied().collect();
            let diameter = both.iter().map(|&i| both.iter().map(|&j| d(i, j)).fold(0.0, f64::max)).fold(0.0, f64::max);
            if forced.contains(&ra) || forced.contains(&rb) || diameter <= MERGE_DIAMETER_M {
                uf.0[ra] = rb;
                members.remove(&ra);
                members.insert(rb, both);
                if forced.contains(&ra) {
                    forced.insert(rb);
                }
            }
        }
        for i in 0..ns.len() {
            let root = uf.find(i);
            out.insert((level, ns[i].1), (level, root));
        }
    }
    out
}

pub fn read(edges: &[DrivingEdge], ways: &[Way]) -> Streets {
    let way_by_id: HashMap<i64, &Way> = ways.iter().map(|w| (w.id, w)).collect();
    // ---- the roads: one for each driving edge and pair of ends, not inside a car park or into a property
    let mut seen: BTreeSet<(i64, i64, i64)> = BTreeSet::new();
    let mut roads: Vec<Road> = Vec::new();
    for e in edges {
        if matches!(way_by_id.get(&e.osm_id).and_then(|w| w.tags.get("service")).map(String::as_str), Some("parking_aisle") | Some("driveway")) {
            continue;
        }
        if !seen.insert((e.osm_id, e.source.min(e.target), e.source.max(e.target))) {
            continue;
        }
        roads.push(Road { level: e.level.clamp(LEVELS.0, LEVELS.1), osm_id: e.osm_id, name: e.name.as_deref().filter(|n| !n.is_empty()), src: e.source, dst: e.target, oneway: e.oneway, line: &e.line });
    }
    let n = roads.len();
    let mut degree: HashMap<(i64, i64), usize> = HashMap::new();
    let mut node_xy: HashMap<(i64, i64), (f64, f64)> = HashMap::new();
    let mut node_order: Vec<(i64, i64)> = Vec::new();
    for r in &roads {
        for (node, c) in [(r.src, r.line.0.first()), (r.dst, r.line.0.last())] {
            if let Some(c) = c {
                *degree.entry((r.level, node)).or_default() += 1;
                if node_xy.insert((r.level, node), (c.x, c.y)).is_none() {
                    node_order.push((r.level, node));
                }
            }
        }
    }

    // ---- 1. streets: the edges of one name (or one way) joined at shared nodes
    let mut parent = Uf::new(n);
    let mut first: HashMap<(i64, Option<&str>, i64, i64), usize> = HashMap::new();
    for (i, r) in roads.iter().enumerate() {
        let group = (r.level, r.name, if r.name.is_some() { 0 } else { r.osm_id });
        for node in [r.src, r.dst] {
            let other = *first.entry((group.0, group.1, group.2, node)).or_insert(i);
            if other != i {
                parent.union(i, other);
            }
        }
    }

    // ---- 2. dual-carriageway pairs: one-way edges of one name, opposite directions, alongside
    let ids: Vec<usize> = (0..n).filter(|&i| roads[i].oneway && roads[i].name.is_some()).collect();
    let boxes = Index::new(ids.iter().map(|&i| roads[i].line.bounding_rect().map(|r| geo::Rect::new(geo::Coord { x: r.min().x - DUAL_CARRIAGEWAY_M, y: r.min().y - DUAL_CARRIAGEWAY_M }, geo::Coord { x: r.max().x + DUAL_CARRIAGEWAY_M, y: r.max().y + DUAL_CARRIAGEWAY_M }))));
    let bearing = |l: &LineString<f64>| (l.0.last().unwrap().x - l.0[0].x).atan2(l.0.last().unwrap().y - l.0[0].y).to_degrees();
    let share = |x: &LineString<f64>, y: &LineString<f64>| NearIndex::new([y]).length_within([x], DUAL_CARRIAGEWAY_M) / Euclidean.length(x).max(1e-9);
    let mut pairs: Vec<(usize, usize)> = Vec::new();
    for (a, &i) in ids.iter().enumerate() {
        let Some(r) = roads[i].line.bounding_rect() else { continue };
        let mut near: Vec<usize> = boxes.query(&r).into_iter().filter(|&b| b > a).collect();
        near.sort();
        for b in near {
            let j = ids[b];
            if roads[i].level != roads[j].level || roads[i].name != roads[j].name {
                continue;
            }
            if Euclidean.distance(roads[i].line, roads[j].line) > DUAL_CARRIAGEWAY_M {
                continue;
            }
            if ((bearing(roads[i].line) - bearing(roads[j].line) + 180.0).rem_euclid(360.0) - 180.0).abs() < DUAL_ANTIPARALLEL_DEG {
                continue;
            }
            if share(roads[i].line, roads[j].line).max(share(roads[j].line, roads[i].line)) >= DUAL_ALONGSIDE {
                pairs.push((i, j));
            }
        }
    }

    // ---- 3. the junctions of the two halves are one junction; a junction on one half forces one on the other
    let mut forced: BTreeSet<(i64, i64)> = BTreeSet::new();
    let mut node_pairs: Vec<(i64, i64, i64)> = Vec::new();
    let mut ends_of_way: HashMap<(i64, i64), BTreeSet<i64>> = HashMap::new();
    for r in &roads {
        ends_of_way.entry((r.level, r.osm_id)).or_default().extend([r.src, r.dst]);
    }
    for &(e, f) in &pairs {
        let lv = roads[e].level;
        for (a, b) in [(e, f), (f, e)] {
            let b_ends = [roads[b].src, roads[b].dst];
            for u in [roads[a].src, roads[a].dst] {
                if degree.get(&(lv, u)).copied().unwrap_or(0) < 3 || ends_of_way.get(&(lv, roads[b].osm_id)).map_or(false, |s| s.contains(&u)) {
                    continue;
                }
                let (Some(pu), true) = (node_xy.get(&(lv, u)), true) else { continue };
                let dist = |v: i64| node_xy.get(&(lv, v)).map_or(f64::INFINITY, |p| (pu.0 - p.0).hypot(pu.1 - p.1));
                let v = *b_ends.iter().min_by(|&&x, &&y| dist(x).partial_cmp(&dist(y)).unwrap()).unwrap();
                if dist(v) <= DUAL_CARRIAGEWAY_M {
                    node_pairs.push((lv, u, v));
                    if degree.get(&(lv, v)).copied().unwrap_or(0) < 3 {
                        forced.insert((lv, v));
                    }
                }
            }
        }
    }
    let is_junction = |lv: i64, nd: i64| degree.get(&(lv, nd)).copied().unwrap_or(0) >= 3 || forced.contains(&(lv, nd));

    // ---- 4. sections: the edges of one street joined at nodes that are not junctions
    let mut sec = Uf::new(n);
    let mut sfirst: HashMap<(usize, i64), usize> = HashMap::new();
    for (i, r) in roads.iter().enumerate() {
        for node in [r.src, r.dst] {
            if !is_junction(r.level, node) {
                let root = parent.find(i);
                let other = *sfirst.entry((root, node)).or_insert(i);
                if other != i {
                    sec.union(i, other);
                }
            }
        }
    }

    // ---- 5. the chains of the two halves that end at the same intersections are one section
    let rings: Vec<BTreeSet<i64>> = ways.iter().filter(|w| matches!(w.tags.get("junction").map(String::as_str), Some("roundabout") | Some("circular"))).map(|w| w.refs.iter().copied().collect()).collect();
    let jnodes: Vec<(i64, i64, f64, f64)> = node_order.iter().filter(|&&(lv, nd)| is_junction(lv, nd)).map(|&(lv, nd)| (lv, nd, node_xy[&(lv, nd)].0, node_xy[&(lv, nd)].1)).collect();
    let cluster_of = clusters(&jnodes, &rings, &node_pairs);
    let mut chain_root: Vec<usize> = (0..n).map(|i| sec.find(i)).collect();
    let mut ends: HashMap<usize, BTreeSet<(i64, usize)>> = HashMap::new();
    for i in 0..n {
        for nd in [roads[i].src, roads[i].dst] {
            if let Some(c) = cluster_of.get(&(roads[i].level, nd)) {
                ends.entry(chain_root[i]).or_default().insert(*c);
            }
        }
    }
    let chain_of = chain_root.clone();
    for &(e, f) in &pairs {
        let (ra, rb) = (sec.find(chain_of[e]), sec.find(chain_of[f]));
        if ra != rb && ends.get(&chain_of[e]) == ends.get(&chain_of[f]) {
            sec.0[ra] = rb;
            parent.union(e, f);
        }
    }
    for i in 0..n {
        chain_root[i] = sec.find(i);
    }

    // ---- 6. ids: the street is k<level>-<smallest way id>
    let mut smallest_way: HashMap<usize, i64> = HashMap::new();
    for i in 0..n {
        let r = parent.find(i);
        let e = smallest_way.entry(r).or_insert(roads[i].osm_id);
        *e = (*e).min(roads[i].osm_id);
    }
    let street_of = |i: usize, parent: &mut Uf| format!("k{}-{}", roads[i].level, smallest_way[&parent.find(i)]);
    let mut way_street = BTreeMap::new();
    for i in 0..n {
        if is_junction(roads[i].level, roads[i].src) || is_junction(roads[i].level, roads[i].dst) {
            way_street.insert(format!("w{}", roads[i].osm_id), street_of(i, &mut parent));
        }
    }

    // ---- the name of a street: the commonest name of its sections' names, each the commonest name of its roads
    let mode = |names: Vec<&str>| -> Option<String> {
        let mut count: Vec<(&str, usize)> = Vec::new();
        for n in names {
            match count.iter_mut().find(|c| c.0 == n) {
                Some(c) => c.1 += 1,
                None => count.push((n, 1)),
            }
        }
        count.iter().max_by(|a, b| a.1.cmp(&b.1).then(std::cmp::Ordering::Greater)).map(|c| c.0.to_string())
    };
    let mut section_names: BTreeMap<usize, Vec<&str>> = BTreeMap::new();
    for i in 0..n {
        if let Some(nm) = roads[i].name {
            section_names.entry(chain_root[i]).or_default().push(nm);
        }
    }
    let mut street_names: BTreeMap<String, (i32, Vec<String>)> = BTreeMap::new();
    for (sec_root, names) in &section_names {
        let i = (0..n).find(|&i| chain_root[i] == *sec_root).unwrap();
        if let Some(nm) = mode(names.clone()) {
            let e = street_names.entry(street_of(i, &mut parent)).or_insert((roads[i].level as i32, vec![]));
            e.1.push(nm);
        }
    }
    let mut name_street = BTreeMap::new();
    for (street, (level, names)) in street_names {
        if let Some(nm) = mode(names.iter().map(String::as_str).collect()) {
            name_street.insert((nm, level), street);
        }
    }
    Streets { way_street, name_street }
}
