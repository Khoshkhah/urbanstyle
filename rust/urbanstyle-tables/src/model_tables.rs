//! The tables of the page from the rows of the model: the columns and their order are those of `product.COLUMNS` (docs/design/tables.md).
//! A shape column other than `geometry` (an axis, a kerb) is left out, as the page's publisher leaves it out.
use crate::{Geom, Table};
use std::collections::BTreeMap;
use urbanstyle_checks::Check;
use urbanstyle_geo::ops::Mp;
use urbanstyle_ground::surfaces::Surface;
use urbanstyle_model::elements::ElementRow;
use urbanstyle_model::objects::ObjectRow;
use urbanstyle_model::registry::Registered;
use urbanstyle_model::Output;

pub struct Parts<'a> {
    pub model: &'a Output,
    pub elements: &'a [ElementRow],
    pub objects: &'a [ObjectRow],
    pub surfaces: &'a [Surface],
    pub checks: &'a [Check],
    pub registry: &'a [Registered],
    pub uids: &'a BTreeMap<(&'static str, String), String>,
    pub area_name: Option<&'a str>,
    pub area: &'a Mp,
    pub zone: u32,
    pub built: &'a str,
}

fn s(x: &str) -> Option<String> {
    Some(x.to_string())
}

fn so(x: &Option<String>) -> Option<String> {
    x.clone()
}

fn json_sides(v: &Option<Vec<urbanstyle_model::BlockSideIn>>) -> Option<String> {
    v.as_ref().map(|v| {
        let items: Vec<serde_json::Value> = v
            .iter()
            .map(|x| serde_json::json!({"way": format!("w{}", x.way), "name": x.name, "class": x.class, "distance_m": x.distance_m, "set_by": x.basis, "method": x.method}))
            .collect();
        serde_json::Value::Array(items).to_string()
    })
}

pub fn all_tables(p: &Parts) -> Vec<Table> {
    let m = p.model;
    let z = p.zone;
    let uid = |t: &'static str, id: &str| p.uids.get(&(t, id.to_string())).cloned();
    let mut out = Vec::new();

    // ---- rank 0: the area; the buildings and lots
    {
        let mut t = Table::new("area", z, m.levels.len());
        t.str("area_id", m.levels.iter().map(|l| s(&format!("a{l}"))))
            .str("kind", m.levels.iter().map(|_| s("area")))
            .i32("rank", m.levels.iter().map(|_| Some(0)))
            .str("parent_id", m.levels.iter().map(|_| None))
            .i32("level", m.levels.iter().map(|l| Some(*l)))
            .str("name", m.levels.iter().map(|_| p.area_name.map(String::from)))
            .str("uid", m.levels.iter().map(|l| uid("area", &format!("a{l}"))))
            .str("source", m.levels.iter().map(|_| s("urbanstyle")))
            .str("method", m.levels.iter().map(|_| s("derived")))
            .str("ref", m.levels.iter().map(|_| None))
            .geometry(m.levels.iter().map(|_| Some(Geom::Poly(p.area))));
        out.push(t);
    }
    {
        let e = p.elements;
        let mut t = Table::new("element", z, e.len());
        t.str("element_id", e.iter().map(|r| s(&r.id)))
            .str("kind", e.iter().map(|r| s(&r.kind)))
            .str("class", e.iter().map(|r| so(&r.class)))
            .str("subtype", e.iter().map(|_| None))
            .str("name", e.iter().map(|r| so(&r.name)))
            .i64("osm_id", e.iter().map(|_| None))
            .str("source_id", e.iter().map(|r| s(&r.id)))
            .str("uid", e.iter().map(|r| uid("element", &r.id)))
            .bool("oneway", e.iter().map(|_| None))
            .i32("lanes_forward", e.iter().map(|_| None))
            .i32("lanes_backward", e.iter().map(|_| None))
            .f64("width_m", e.iter().map(|_| None))
            .str("width_src", e.iter().map(|_| None))
            .i32("level_min", e.iter().map(|r| Some(r.level_min)))
            .i32("level_max", e.iter().map(|r| Some(r.level_max)))
            .str("level_src", e.iter().map(|r| s(&r.level_src)))
            .i32("floors", e.iter().map(|r| r.floors))
            .f64("height_m", e.iter().map(|r| r.height_m))
            .str("use", e.iter().map(|r| so(&r.usage)))
            .str("use_source", e.iter().map(|r| so(&r.use_source)))
            .str("use_method", e.iter().map(|r| so(&r.use_method)))
            .str("ground_use", e.iter().map(|r| so(&r.ground_use)))
            .str("ground_source", e.iter().map(|r| so(&r.ground_source)))
            .str("ground_method", e.iter().map(|r| so(&r.ground_method)))
            .str("source", e.iter().map(|r| s(&r.source)))
            .geometry(e.iter().map(|r| Some(Geom::Poly(&r.geom))));
        out.push(t);
    }

    // ---- rank 1 and 2
    {
        let g = &m.ground;
        let mut t = Table::new("ground", z, g.len());
        t.str("ground_id", g.iter().map(|r| s(&r.id)))
            .str("kind", g.iter().map(|r| s(&r.kind)))
            .i32("rank", g.iter().map(|_| Some(1)))
            .str("parent_id", g.iter().map(|r| s(&r.parent)))
            .i32("level", g.iter().map(|r| Some(r.level)))
            .str("name", g.iter().map(|r| so(&r.name)))
            .str("uid", g.iter().map(|r| uid("ground", &r.id)))
            .str("sides", g.iter().map(|r| json_sides(&r.sides)))
            .f64("width_m", g.iter().map(|r| r.width_m))
            .str("width_source", g.iter().map(|r| so(&r.width_source)))
            .str("width_method", g.iter().map(|r| so(&r.width_method)))
            .str("source", g.iter().map(|r| so(&r.source)))
            .str("method", g.iter().map(|r| so(&r.method)))
            .str("ref", g.iter().map(|r| so(&r.r#ref)))
            .geometry(g.iter().map(|r| Some(Geom::Poly(&r.geom))));
        out.push(t);
    }
    {
        let r = &m.stretches;
        let mut t = Table::new("stretch", z, r.len());
        t.str("stretch_id", r.iter().map(|x| s(&x.id)))
            .str("kind", r.iter().map(|x| s(&x.kind)))
            .i32("rank", r.iter().map(|_| Some(2)))
            .str("parent_id", r.iter().map(|x| so(&x.parent)))
            .i32("level", r.iter().map(|x| Some(x.level)))
            .str("name", r.iter().map(|x| so(&x.name)))
            .str("uid", r.iter().map(|x| uid("stretch", &x.id)))
            .str("street_id", r.iter().map(|x| so(&x.street)))
            .list("ways", r.iter().map(|x| x.ways.as_slice()))
            .str("nodes", r.iter().map(|x| Some(format!("[{}]", x.nodes.iter().map(|n| n.to_string()).collect::<Vec<_>>().join(", ")))))
            .str("class", r.iter().map(|x| so(&x.class)))
            .bool("oneway", r.iter().map(|x| x.oneway))
            .f64("length_m", r.iter().map(|x| x.length))
            .str("source", r.iter().map(|_| s("urbanstyle")))
            .str("method", r.iter().map(|_| s("derived")))
            .str("ref", r.iter().map(|x| s(&x.r#ref)))
            .geometry(r.iter().map(|x| Some(Geom::Poly(&x.geom))));
        out.push(t);
    }
    {
        let r = &m.plot_pieces;
        let mut t = Table::new("plot_piece", z, r.len());
        t.str("piece_id", r.iter().map(|x| s(&x.id)))
            .str("kind", r.iter().map(|x| s(&x.kind)))
            .i32("rank", r.iter().map(|_| Some(2)))
            .str("parent_id", r.iter().map(|x| so(&x.parent)))
            .i32("level", r.iter().map(|x| Some(x.level)))
            .str("name", r.iter().map(|x| so(&x.name)))
            .str("uid", r.iter().map(|x| uid("plot_piece", &x.id)))
            .f64("width_m", r.iter().map(|x| x.width_m))
            .str("width_source", r.iter().map(|x| so(&x.width_source)))
            .str("width_method", r.iter().map(|x| so(&x.width_method)))
            .list("surfaces", r.iter().map(|x| x.surfaces.as_slice()))
            .str("source", r.iter().map(|x| so(&x.source)))
            .str("method", r.iter().map(|x| so(&x.method)))
            .str("ref", r.iter().map(|x| so(&x.r#ref)))
            .geometry(r.iter().map(|x| Some(Geom::Poly(&x.geom))));
        out.push(t);
    }
    {
        let r = &m.streets;
        let mut t = Table::new("street", z, r.len());
        t.str("street_id", r.iter().map(|x| s(&x.id)))
            .str("name", r.iter().map(|x| so(&x.name)))
            .i32("level", r.iter().map(|x| Some(x.level)))
            .list("sections", r.iter().map(|x| x.sections.as_slice()))
            .list("intersections", r.iter().map(|x| x.intersections.as_slice()))
            .geometry(r.iter().map(|x| Some(Geom::Poly(&x.geom))));
        out.push(t);
    }
    {
        let r = &m.arms;
        let mut t = Table::new("arm", z, r.len());
        t.str("intersection_id", r.iter().map(|x| s(&x.intersection)))
            .str("street_id", r.iter().map(|x| so(&x.street)))
            .str("section_id", r.iter().map(|x| s(&x.section)))
            .str("way", r.iter().map(|x| so(&x.way)))
            .i32("level", r.iter().map(|x| Some(x.level)));
        out.push(t);
    }

    // ---- rank 3 to 6
    {
        let r = &m.spaces;
        let mut t = Table::new("space", z, r.len());
        t.str("space_id", r.iter().map(|x| s(&x.id)))
            .str("kind", r.iter().map(|x| s(&x.kind)))
            .i32("rank", r.iter().map(|_| Some(3)))
            .str("parent_id", r.iter().map(|x| s(&x.parent)))
            .i32("level", r.iter().map(|x| Some(x.level)))
            .str("name", r.iter().map(|x| so(&x.name)))
            .str("uid", r.iter().map(|x| uid("space", &x.id)))
            .f64("s_from", r.iter().map(|x| x.s_from))
            .f64("s_to", r.iter().map(|x| x.s_to))
            .f64("width_m", r.iter().map(|x| x.width))
            .bool("oneway", r.iter().map(|x| x.oneway))
            .f64("length_m", r.iter().map(|x| x.length))
            .f64("left_extra", r.iter().map(|x| x.left_extra))
            .list("predecessors", r.iter().map(|x| x.pred.as_slice()))
            .list("successors", r.iter().map(|x| x.succ.as_slice()))
            .str("source", r.iter().map(|_| s("urbanstyle")))
            .str("method", r.iter().map(|_| s("derived")))
            .str("ref", r.iter().map(|_| None))
            .geometry(r.iter().map(|x| Some(Geom::Poly(&x.geom))));
        out.push(t);
    }
    {
        let r = &m.junctions;
        let mut t = Table::new("junction", z, r.len());
        t.str("intersection_id", r.iter().map(|x| s(&x.intersection)))
            .i64("node_id", r.iter().map(|x| Some(x.node)))
            .i32("level", r.iter().map(|x| Some(x.level)))
            .str("cluster_id", r.iter().map(|x| so(&x.cluster)))
            .str("space_id", r.iter().map(|x| so(&x.space)));
        out.push(t);
    }
    {
        let r = &m.sides;
        let mut t = Table::new("side", z, r.len());
        t.str("side_id", r.iter().map(|x| s(&x.id)))
            .str("kind", r.iter().map(|x| s(&x.kind)))
            .i32("rank", r.iter().map(|_| Some(4)))
            .str("parent_id", r.iter().map(|x| s(&x.parent)))
            .i32("level", r.iter().map(|x| Some(x.level)))
            .str("name", r.iter().map(|_| None))
            .str("uid", r.iter().map(|x| uid("side", &x.id)))
            .str("kerb_source", r.iter().map(|x| so(&x.kerb_source)))
            .str("kerb_method", r.iter().map(|x| so(&x.kerb_method)))
            .str("source", r.iter().map(|_| s("urbanstyle")))
            .str("method", r.iter().map(|_| s("derived")))
            .str("ref", r.iter().map(|_| None))
            .geometry(r.iter().map(|x| Some(Geom::Poly(&x.geom))));
        out.push(t);
    }
    {
        let r = &m.parts;
        let mut t = Table::new("part", z, r.len());
        t.str("part_id", r.iter().map(|x| s(&x.id)))
            .str("kind", r.iter().map(|x| s(&x.typ)))
            .i32("rank", r.iter().map(|_| Some(5)))
            .str("parent_id", r.iter().map(|x| s(&x.side)))
            .i32("level", r.iter().map(|x| Some(x.level)))
            .str("name", r.iter().map(|_| None))
            .str("uid", r.iter().map(|x| uid("part", &x.id)))
            .str("space_id", r.iter().map(|x| s(&x.space)))
            .str("arm", r.iter().map(|_| None))
            .str("direction", r.iter().map(|x| so(&x.direction)))
            .i32("lane", r.iter().map(|x| x.lane.map(|v| v as i32)))
            .str("lane_id", r.iter().map(|x| so(&x.extra.lane_id)))
            .f64("s_from", r.iter().map(|x| x.st[0]))
            .f64("s_to", r.iter().map(|x| x.st[1]))
            .f64("t_from", r.iter().map(|x| x.st[2]))
            .f64("t_to", r.iter().map(|x| x.st[3]))
            .list("predecessors", r.iter().map(|x| x.pred.as_slice()))
            .list("successors", r.iter().map(|x| x.succ.as_slice()))
            .f64("width_m", r.iter().map(|x| x.width_m))
            .str("width_source", r.iter().map(|x| so(&x.width_source)))
            .str("width_method", r.iter().map(|x| so(&x.extra.width_method)))
            .f64("length_m", r.iter().map(|x| x.length_m))
            .str("position_source", r.iter().map(|_| None))
            .str("position_method", r.iter().map(|_| None))
            .str("position_ref", r.iter().map(|_| None))
            .str("road", r.iter().map(|x| so(&x.road)))
            .str("road_class", r.iter().map(|x| so(&x.extra.road_class)))
            .f64("speed", r.iter().map(|_| None))
            .str("surface", r.iter().map(|_| None))
            .str("lit", r.iter().map(|_| None))
            .str("road_lanes", r.iter().map(|_| None))
            .str("oneway", r.iter().map(|x| so(&x.extra.oneway)))
            .str("holds", r.iter().map(|_| None))
            .str("rule", r.iter().map(|_| None))
            .str("source", r.iter().map(|x| so(&x.extra.source)))
            .str("method", r.iter().map(|x| so(&x.extra.method)))
            .str("ref", r.iter().map(|x| so(&x.r#ref)))
            .geometry(r.iter().map(|x| Some(Geom::Poly(&x.geom))));
        out.push(t);
    }
    {
        let r = &m.marks;
        let mut t = Table::new("mark", z, r.len());
        t.str("mark_id", r.iter().map(|x| s(&x.id)))
            .str("kind", r.iter().map(|x| s(&x.kind)))
            .i32("rank", r.iter().map(|_| Some(6)))
            .str("parent_id", r.iter().map(|x| so(&x.parent)))
            .i32("level", r.iter().map(|x| Some(x.level)))
            .str("name", r.iter().map(|_| None))
            .str("uid", r.iter().map(|x| uid("mark", &x.id)))
            .i32("parent_rank", r.iter().map(|x| Some(x.parent_rank)))
            .str("space_id", r.iter().map(|x| s(&x.space)))
            .f64("s_from", r.iter().map(|x| x.st[0]))
            .f64("s_to", r.iter().map(|x| x.st[1]))
            .f64("t_from", r.iter().map(|x| x.st[2]))
            .f64("t_to", r.iter().map(|x| x.st[3]))
            .f64("width_m", r.iter().map(|_| None))
            .str("width_source", r.iter().map(|_| None))
            .str("width_method", r.iter().map(|_| None))
            .f64("length_m", r.iter().map(|x| Some((x.lines.iter().map(urbanstyle_geo::lines::length).sum::<f64>() * 10.0).round() / 10.0)))
            .str("source", r.iter().map(|x| so(&x.source)))
            .str("method", r.iter().map(|x| so(&x.method)))
            .str("ref", r.iter().map(|x| so(&x.reference)))
            .geometry(r.iter().map(|x| Some(Geom::Lines(&x.lines))));
        out.push(t);
    }
    {
        let r = &m.turns;
        let mut t = Table::new("turn", z, r.len());
        t.str("space_id", r.iter().map(|x| s(&x.space)))
            .i32("level", r.iter().map(|x| Some(x.level)))
            .str("from_edge", r.iter().map(|x| so(&x.from_edge)))
            .i32("from_lane", r.iter().map(|x| x.from_lane.map(|v| v as i32)))
            .str("to_edge", r.iter().map(|x| so(&x.to_edge)))
            .i32("to_lane", r.iter().map(|x| x.to_lane.map(|v| v as i32)))
            .str("turn", r.iter().map(|x| so(&x.turn)))
            .str("vehicles", r.iter().map(|x| so(&x.vehicles)))
            .str("condition", r.iter().map(|_| None))
            .str("source", r.iter().map(|x| so(&x.source)))
            .geometry(r.iter().map(|x| Some(Geom::Lines(&x.lines))));
        out.push(t);
    }
    {
        let r = &m.approaches;
        let mut t = Table::new("approach", z, r.len());
        t.str("intersection_id", r.iter().map(|x| s(&x.unit)))
            .i32("level", r.iter().map(|x| Some(x.level)))
            .str("from_edge", r.iter().map(|x| so(&x.from_edge)))
            .i32("lane", r.iter().map(|x| x.lane.map(|v| v as i32)))
            .i32("moves", r.iter().map(|x| x.moves.map(|v| v as i32)))
            .str("ways", r.iter().map(|x| so(&x.ways)))
            .bool("arrow", r.iter().map(|x| x.arrow))
            .str("no_arrow_because", r.iter().map(|x| so(&x.no_arrow_because)));
        out.push(t);
    }

    // ---- on the tree
    {
        let r = p.objects;
        let mut t = Table::new("object", z, r.len());
        t.str("object_id", r.iter().map(|x| s(&x.id)))
            .str("kind", r.iter().map(|x| s(&x.kind)))
            .str("uid", r.iter().map(|x| uid("object", &x.id)))
            .i32("level", r.iter().map(|x| Some(x.level)))
            .str("space_id", r.iter().map(|x| so(&x.space)))
            .str("part_id", r.iter().map(|x| so(&x.part)))
            .f64("near_m", r.iter().map(|x| x.near_m))
            .str("name", r.iter().map(|x| so(&x.name)))
            .str("attrs", r.iter().map(|x| Some(serde_json::to_string(&x.attrs).unwrap())))
            .f64("width_m", r.iter().map(|x| x.width_m))
            .str("width_source", r.iter().map(|x| so(&x.width_source)))
            .str("width_method", r.iter().map(|x| so(&x.width_method)))
            .f64("height_m", r.iter().map(|x| x.height_m))
            .str("height_source", r.iter().map(|x| so(&x.height_source)))
            .str("height_method", r.iter().map(|x| so(&x.height_method)))
            .str("sources", r.iter().map(|_| s("osm")))
            .str("refs", r.iter().map(|x| s(&x.id)))
            .str("source", r.iter().map(|_| s("osm")))
            .str("method", r.iter().map(|_| s("mapped")))
            .geometry(r.iter().map(|x| Some(Geom::Point(x.point))));
        out.push(t);
    }
    {
        let polys: Vec<Mp> = p.surfaces.iter().map(|x| Mp::new(vec![x.geom.clone()])).collect();
        let r = p.surfaces;
        let mut t = Table::new("surface", z, r.len());
        t.str("surface_id", r.iter().map(|x| s(&x.id)))
            .str("ground_id", r.iter().map(|x| s(&x.ground)))
            .str("kind", r.iter().map(|x| s(&x.kind)))
            .i32("level", r.iter().map(|_| Some(0)))
            .str("source", r.iter().map(|x| s(&x.source)))
            .str("method", r.iter().map(|x| s(&x.method)))
            .str("ref", r.iter().map(|x| so(&x.r#ref)))
            .geometry(polys.iter().map(|g| Some(Geom::Poly(g))));
        out.push(t);
    }

    // ---- the data about the data
    {
        let r = p.checks;
        let mut t = Table::new("check", z, r.len());
        t.str("check_id", r.iter().map(|x| s(x.id)))
            .str("kind", r.iter().map(|x| s(if x.hard { "fault" } else { "info" })))
            .str("status", r.iter().map(|x| s(x.status())))
            .i32("count", r.iter().map(|x| Some(x.count as i32)))
            .str("what", r.iter().map(|x| s(&x.what)))
            .str("items", r.iter().map(|_| s("[]")))
            .str("checked", r.iter().map(|_| s(p.built)));
        out.push(t);
    }
    {
        let r = p.registry;
        let mut t = Table::new("registry", z, r.len());
        t.str("profile", r.iter().map(|x| s(&x.profile)))
            .str("uid", r.iter().map(|x| s(&x.uid)))
            .str("kind", r.iter().map(|x| s(&x.kind)))
            .str("first_seen", r.iter().map(|x| s(&x.first_seen)))
            .str("last_seen", r.iter().map(|x| s(&x.last_seen)));
        out.push(t);
    }
    {
        let r = urbanstyle_model::style::STYLE;
        let mut t = Table::new("style", z, r.len());
        t.str("table", r.iter().map(|x| s(x.0)))
            .i32("rank", r.iter().map(|x| x.1))
            .str("kind", r.iter().map(|x| s(x.2)))
            .i32("draw_order", r.iter().map(|x| Some(x.3)))
            .str("form", r.iter().map(|x| s(x.4)))
            .str("colour", r.iter().map(|x| s(x.5)))
            .str("dash", r.iter().map(|x| x.6.map(|d| format!("[{:?}, {:?}]", d[0], d[1]))))
            .f64("raise_m", r.iter().map(|x| Some(x.7)));
        out.push(t);
    }
    {
        let r = urbanstyle_model::style::CODE;
        let mut t = Table::new("code", z, r.len());
        t.str("kind", r.iter().map(|x| s(x.0)))
            .str("citygml", r.iter().map(|x| x.1.map(String::from)))
            .str("opendrive", r.iter().map(|x| x.2.map(String::from)))
            .str("opensidewalks", r.iter().map(|x| x.3.map(String::from)))
            .str("ifc", r.iter().map(|x| x.4.map(String::from)));
        out.push(t);
    }
    out
}
