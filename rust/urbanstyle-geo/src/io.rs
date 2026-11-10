//! Geometry from JSON coordinate arrays (the GeoJSON layout), for the tests against the Python results and for the data that the Python
//! reference writes. Metres in, metres out.
use geo::{Coord, LineString, MultiPolygon, Polygon};
use serde_json::Value;

fn coord(v: &Value) -> Option<Coord<f64>> {
    let a = v.as_array()?;
    Some(Coord { x: a.first()?.as_f64()?, y: a.get(1)?.as_f64()? })
}

pub fn line_string(v: &Value) -> Option<LineString<f64>> {
    Some(LineString::new(v.as_array()?.iter().map(coord).collect::<Option<Vec<_>>>()?))
}

/// `[exterior, hole, ...]`
pub fn polygon(v: &Value) -> Option<Polygon<f64>> {
    let rings = v.as_array()?.iter().map(line_string).collect::<Option<Vec<_>>>()?;
    let mut it = rings.into_iter();
    Some(Polygon::new(it.next()?, it.collect()))
}

/// `[polygon, polygon, ...]`
pub fn multi_polygon(v: &Value) -> Option<MultiPolygon<f64>> {
    Some(MultiPolygon::new(v.as_array()?.iter().map(polygon).collect::<Option<Vec<_>>>()?))
}
