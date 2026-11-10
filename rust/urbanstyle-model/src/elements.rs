//! The building and lot rows of `urban.element`: the levels of a building from its OSM tags (`container.BUILD` and `CLAMP`), its floors and
//! height, and what it is used for (`buildings.py`: the OSM tag, and the shops and offices OSM maps inside its footprint). The city data of
//! Vancouver (`buildings.city`, the storefronts) is not read.
use geo::BoundingRect;
use std::collections::BTreeMap;
use urbanstyle_geo::index::{Index, SegIndex};
use urbanstyle_geo::ops::{self, Mp};

/// The height of a floor when only the height is known (`container.FLOOR_M`).
pub const FLOOR_M: f64 = 3.0;
/// Only these levels are kept; a span is clamped to them (`container.LEVELS`).
pub const LEVELS: (i32, i32) = (-5, 5);

#[derive(Clone)]
pub struct BuildingIn {
    /// `way` or `relation`.
    pub osm_type: String,
    pub osm_id: i64,
    pub name: Option<String>,
    pub kind: Option<String>,
    pub tags: BTreeMap<String, String>,
    pub geom: Mp,
}

#[derive(Clone)]
pub struct PoiIn {
    pub tags: BTreeMap<String, String>,
    pub point: geo::Coord<f64>,
}

#[derive(Clone)]
pub struct LotIn {
    pub id: String,
    pub typ: String,
    pub name: Option<String>,
    pub level: i32,
    pub geom: Mp,
}

pub struct ElementRow {
    pub id: String,
    pub kind: String,
    pub class: Option<String>,
    pub name: Option<String>,
    pub level_min: i32,
    pub level_max: i32,
    pub level_src: String,
    pub floors: Option<i32>,
    pub height_m: Option<f64>,
    pub usage: Option<String>,
    pub use_source: Option<String>,
    pub use_method: Option<String>,
    pub ground_use: Option<String>,
    pub ground_source: Option<String>,
    pub ground_method: Option<String>,
    pub source: String,
    pub geom: Mp,
}

/// DuckDB's `try_cast(text AS INTEGER)`: a number, rounded half away from zero; none for text that is not one.
pub fn try_int(s: &str) -> Option<i32> {
    let t = s.trim();
    let ok = !t.is_empty()
        && t.chars().enumerate().all(|(i, c)| c.is_ascii_digit() || c == '.' || (i == 0 && (c == '-' || c == '+')))
        && t.chars().filter(|c| *c == '.').count() <= 1
        && t.chars().any(|c| c.is_ascii_digit());
    ok.then(|| t.parse::<f64>().ok()).flatten().map(|x| x.round() as i32)
}

/// `try_cast(nullif(regexp_extract(height, '^[0-9]+([.][0-9]+)?', 0), '') AS DOUBLE)`: the number at the start of the text.
pub fn height_of(s: &str) -> Option<f64> {
    let b = s.as_bytes();
    let digits = b.iter().take_while(|c| c.is_ascii_digit()).count();
    if digits == 0 {
        return None;
    }
    let mut end = digits;
    if b.get(end) == Some(&b'.') {
        let frac = b[end + 1..].iter().take_while(|c| c.is_ascii_digit()).count();
        if frac > 0 {
            end += 1 + frac;
        }
    }
    s[..end].parse().ok()
}

/// OSM `building` or `building:use` value -> use; values not here (yes, roof, ...) say nothing.
fn use_of(tag: &str) -> Option<&'static str> {
    Some(match tag {
        "apartments" | "residential" | "house" | "detached" | "semidetached_house" | "terrace" | "dormitory" | "bungalow" | "houseboat" => "residential",
        "retail" | "supermarket" | "kiosk" => "retail",
        "commercial" => "commercial",
        "office" => "office",
        "industrial" | "warehouse" | "manufacture" => "industrial",
        "church" | "chapel" | "mosque" | "temple" | "synagogue" | "religious" | "hospital" | "community_hall" | "theatre" | "fire_station" | "government" | "public" | "civic"
        | "school" | "college" | "university" | "library" | "museum" | "kindergarten" | "police" | "transportation" | "train_station" => "civic",
        "garage" | "garages" | "parking" | "carport" | "shed" | "service" => "ancillary",
        _ => return None,
    })
}

const FOOD: [&str; 8] = ["restaurant", "cafe", "fast_food", "bar", "pub", "ice_cream", "food_court", "biergarten"];
const SERVICE_SHOP: [&str; 9] = ["hairdresser", "beauty", "massage", "laundry", "dry_cleaning", "tattoo", "travel_agency", "copyshop", "optician"];
const SERVICE: [&str; 9] = ["bank", "doctors", "dentist", "clinic", "pharmacy", "veterinary", "post_office", "bureau_de_change", "money_transfer"];
const LEISURE: [&str; 8] = ["cinema", "theatre", "nightclub", "arts_centre", "gym", "fitness_centre", "sports_centre", "dance"];
const CIVIC: [&str; 9] = ["place_of_worship", "library", "school", "kindergarten", "community_centre", "townhall", "police", "fire_station", "courthouse"];

/// The use an OSM point inside a building stands for, or none for what is no business (a bench, a post box).
pub fn poi_use(t: &BTreeMap<String, String>) -> Option<&'static str> {
    let g = |k: &str| t.get(k).map(String::as_str);
    let (a, s) = (g("amenity"), g("shop"));
    let truthy = |k: &str| g(k).map_or(false, |v| !v.is_empty());
    if matches!(s, Some("vacant") | Some("no")) || truthy("disused:shop") || truthy("vacant") {
        return Some("vacant");
    }
    if a.map_or(false, |a| FOOD.contains(&a)) {
        return Some("food & drink");
    }
    if s.map_or(false, |s| SERVICE_SHOP.contains(&s)) || a.map_or(false, |a| SERVICE.contains(&a)) || truthy("healthcare") || truthy("craft") {
        return Some("services");
    }
    if s.map_or(false, |s| !s.is_empty()) {
        return Some("retail");
    }
    if a.map_or(false, |a| LEISURE.contains(&a)) || g("leisure").map_or(false, |l| LEISURE.contains(&l)) {
        return Some("leisure");
    }
    if a.map_or(false, |a| CIVIC.contains(&a)) || a == Some("social_facility") {
        return Some("civic");
    }
    if truthy("office") {
        return Some("office");
    }
    None
}

/// What the points inside a building say: (use, source, method, what, on the ground floor, name in lower case).
type Found = (&'static str, &'static str, &'static str, bool);

pub fn build(buildings: &[BuildingIn], pois: &[PoiIn], lots: &[LotIn]) -> Vec<ElementRow> {
    let blds: Vec<Mp> = buildings.iter().map(|b| ops::orient(&b.geom)).collect();
    let index = Index::new(blds.iter().map(|m| m.bounding_rect()));
    let segs: Vec<SegIndex> = blds.iter().map(SegIndex::new).collect();
    let mut found: Vec<Vec<Found>> = vec![vec![]; buildings.len()];
    for p in pois {
        let Some(u) = poi_use(&p.tags) else { continue };
        let r = geo::Rect::new(p.point, p.point);
        for k in index.query(&r) {
            if segs[k].contains(p.point) {
                let ground = matches!(p.tags.get("level").map(|l| l.split(';').next().unwrap_or("").trim()).unwrap_or("0"), "0" | "");
                found[k].push((u, "osm", "mapped", ground));
            }
        }
    }
    let mut rows = Vec::new();
    for (k, b) in buildings.iter().enumerate() {
        let t = |key: &str| b.tags.get(key).map(String::as_str);
        let fl = t("building:levels").and_then(try_int);
        let ug = t("building:levels:underground").and_then(try_int);
        let mn = t("building:min_level").and_then(try_int);
        let h = t("height").and_then(height_of);
        let under = t("location") == Some("underground");
        let (mn0, ug0) = (mn.unwrap_or(0), ug.unwrap_or(0));
        let by_height = h.map(|h| (h / FLOOR_M).round() as i32);
        let (mut lmin, mut lmax) = if under { (-fl.or(ug).unwrap_or(1), -1) } else { (mn0 - ug0, fl.or(by_height).unwrap_or(1) - 1 + mn0) };
        let level_src = if fl.is_some() { "num_floors" } else if h.is_some() { "height" } else { "chosen" };
        // (the clamp: a building wholly outside the kept levels is dropped)
        if lmin > LEVELS.1 || lmax < LEVELS.0 {
            continue;
        }
        lmin = lmin.max(LEVELS.0);
        lmax = lmax.min(LEVELS.1);
        let floors = fl.or(by_height);
        let height = h.or(fl.map(|f| f as f64 * FLOOR_M)).map(|x| (x * 10.0).round() / 10.0);

        // the use: the OSM tag, then the businesses on the ground floor
        let tag = t("building:use").filter(|s| !s.is_empty()).or(t("building"));
        let mut usage = tag.and_then(use_of);
        let f = &found[k];
        let g: Vec<&Found> = f.iter().filter(|x| x.3).collect();
        let mut counts: Vec<(&str, usize)> = Vec::new();
        for x in g.iter().filter(|x| x.0 != "vacant") {
            match counts.iter_mut().find(|c| c.0 == x.0) {
                Some(c) => c.1 += 1,
                None => counts.push((x.0, 1)),
            }
        }
        let busy = counts.iter().copied().fold(None::<(&str, usize)>, |b, c| match b {
            Some(x) if x.1 >= c.1 => Some(x),
            _ => Some(c),
        });
        let ground: Option<&str> = if let Some((u, _)) = busy {
            Some(u)
        } else if !g.is_empty() {
            Some("vacant")
        } else if usage == Some("residential") {
            Some("residential")
        } else {
            None
        };
        let gsrc: Option<String> = if !g.is_empty() { Some("osm".into()) } else { ground.map(|_| "osm".to_string()) };
        let gmeth: Option<&str> = if !g.is_empty() { Some("mapped") } else { ground.map(|_| "derived") };
        let (mut src, mut meth) = if usage.is_some() { (Some("osm".to_string()), Some("mapped")) } else { (None, None) };
        if matches!(usage, Some("residential") | Some("office")) && busy.is_some() {
            usage = Some("mixed");
            src = Some("osm".into());
            meth = Some("derived");
        } else if usage.is_none() && busy.is_some() {
            usage = Some("commercial");
            src = gsrc.clone();
            meth = Some("derived");
        }
        rows.push(ElementRow {
            id: format!("{}{}", b.osm_type.chars().next().unwrap_or('w'), b.osm_id),
            kind: "building".into(),
            class: b.kind.clone(),
            name: b.name.clone(),
            level_min: lmin,
            level_max: lmax,
            level_src: level_src.into(),
            floors,
            height_m: height,
            usage: usage.map(String::from),
            use_source: src,
            use_method: meth.map(String::from),
            ground_use: ground.map(String::from),
            ground_source: gsrc,
            ground_method: gmeth.map(String::from),
            source: "osm".into(),
            geom: b.geom.clone(),
        });
    }
    for l in lots {
        rows.push(ElementRow {
            id: l.id.clone(),
            kind: "lot".into(),
            class: Some(l.typ.clone()),
            name: l.name.clone(),
            level_min: l.level,
            level_max: l.level,
            level_src: "layer".into(),
            floors: None,
            height_m: None,
            usage: None,
            use_source: None,
            use_method: None,
            ground_use: None,
            ground_source: None,
            ground_method: None,
            source: "osm".into(),
            geom: l.geom.clone(),
        });
    }
    rows
}
