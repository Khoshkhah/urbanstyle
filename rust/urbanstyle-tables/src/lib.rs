//! The tables of the model as Parquet files for the page (docs/design/dashboard.md, "How the page is made"): DuckDB-WASM reads one file for
//! each table. The layout is the page's (`publish._tables`): the plain columns as they are, every other column as text, and for a
//! geometry its GeoJSON in lon/lat (`__g`) with its length and area in metres and its box (`__len`, `__area`, `__x`, `__y`, `__w`, `__s`,
//! `__e`, `__n`). The coordinates of the model are metres in a UTM zone; the page's are degrees.
use arrow_array::{ArrayRef, BooleanArray, Float64Array, Int32Array, Int64Array, RecordBatch, StringArray};
use arrow_schema::{DataType, Field, Schema};
use geo::{Coord, LineString};
use std::path::Path;
use std::sync::Arc;
use urbanstyle_geo::lines;
use urbanstyle_geo::ops::Mp;

pub mod model_tables;
pub use model_tables::all_tables;

/// UTM (WGS 84, northern hemisphere) to lon/lat in degrees: the series of Krueger. `zone`: 32 for Monaco and Sodermalm's west.
pub fn utm_to_lonlat(x: f64, y: f64, zone: u32) -> (f64, f64) {
    const A: f64 = 6378137.0;
    const F: f64 = 1.0 / 298.257223563;
    const K0: f64 = 0.9996;
    let n = F / (2.0 - F);
    let (n2, n3) = (n * n, n * n * n);
    let big_a = A / (1.0 + n) * (1.0 + n2 / 4.0 + n2 * n2 / 64.0);
    let beta = [n / 2.0 - 2.0 * n2 / 3.0 + 37.0 * n3 / 96.0, n2 / 48.0 + n3 / 15.0, 17.0 * n3 / 480.0];
    let delta = [2.0 * n - 2.0 * n2 / 3.0 - 2.0 * n3, 7.0 * n2 / 3.0 - 8.0 * n3 / 5.0, 56.0 * n3 / 15.0];
    let xi = y / (K0 * big_a);
    let eta = (x - 500000.0) / (K0 * big_a);
    let (mut xi_p, mut eta_p) = (xi, eta);
    for (j, b) in beta.iter().enumerate() {
        let k = 2.0 * (j as f64 + 1.0);
        xi_p -= b * (k * xi).sin() * (k * eta).cosh();
        eta_p -= b * (k * xi).cos() * (k * eta).sinh();
    }
    let chi = (xi_p.sin() / eta_p.cosh()).asin();
    let mut lat = chi;
    for (j, d) in delta.iter().enumerate() {
        lat += d * (2.0 * (j as f64 + 1.0) * chi).sin();
    }
    let lon0 = (zone as f64 * 6.0 - 183.0).to_radians();
    let lon = lon0 + eta_p.sinh().atan2(xi_p.cos());
    (lon.to_degrees(), lat.to_degrees())
}

/// A geometry of a row, in metres.
pub enum Geom<'a> {
    Poly(&'a Mp),
    Line(&'a LineString<f64>),
    Lines(&'a [LineString<f64>]),
    Point(Coord<f64>),
}

#[derive(Clone)]
pub enum Data {
    Str(Vec<Option<String>>),
    I32(Vec<Option<i32>>),
    I64(Vec<Option<i64>>),
    F64(Vec<Option<f64>>),
    Bool(Vec<Option<bool>>),
}

pub struct Table {
    pub name: String,
    pub cols: Vec<(String, Data)>,
    zone: u32,
    n: usize,
    geo: Option<GeoCols>,
}

#[derive(Default)]
struct GeoCols {
    g: Vec<Option<String>>,
    len: Vec<Option<f64>>,
    area: Vec<Option<f64>>,
    bbox: Vec<Option<[f64; 4]>>,
    centre: Vec<Option<[f64; 2]>>,
}

fn ring_json(r: &LineString<f64>, zone: u32) -> String {
    let pts: Vec<String> = r.0.iter().map(|c| {
        let (lon, lat) = utm_to_lonlat(c.x, c.y, zone);
        format!("[{lon:.9},{lat:.9}]")
    }).collect();
    format!("[{}]", pts.join(","))
}

impl Table {
    pub fn new(name: &str, zone: u32, n: usize) -> Table {
        Table { name: name.to_string(), cols: Vec::new(), zone, n, geo: None }
    }

    fn check(&self, len: usize, what: &str) {
        assert_eq!(len, self.n, "table {} column {what}: {len} values for {} rows", self.name, self.n);
    }

    pub fn str<I: IntoIterator<Item = Option<String>>>(&mut self, name: &str, v: I) -> &mut Self {
        let v: Vec<_> = v.into_iter().collect();
        self.check(v.len(), name);
        self.cols.push((name.into(), Data::Str(v)));
        self
    }

    pub fn i32<I: IntoIterator<Item = Option<i32>>>(&mut self, name: &str, v: I) -> &mut Self {
        let v: Vec<_> = v.into_iter().collect();
        self.check(v.len(), name);
        self.cols.push((name.into(), Data::I32(v)));
        self
    }

    pub fn i64<I: IntoIterator<Item = Option<i64>>>(&mut self, name: &str, v: I) -> &mut Self {
        let v: Vec<_> = v.into_iter().collect();
        self.check(v.len(), name);
        self.cols.push((name.into(), Data::I64(v)));
        self
    }

    pub fn f64<I: IntoIterator<Item = Option<f64>>>(&mut self, name: &str, v: I) -> &mut Self {
        let v: Vec<_> = v.into_iter().collect();
        self.check(v.len(), name);
        self.cols.push((name.into(), Data::F64(v)));
        self
    }

    pub fn bool<I: IntoIterator<Item = Option<bool>>>(&mut self, name: &str, v: I) -> &mut Self {
        let v: Vec<_> = v.into_iter().collect();
        self.check(v.len(), name);
        self.cols.push((name.into(), Data::Bool(v)));
        self
    }

    /// A list of text, written as DuckDB casts it to text: `[a, b]`.
    pub fn list<'a, I: IntoIterator<Item = &'a [String]>>(&mut self, name: &str, v: I) -> &mut Self {
        self.str(name, v.into_iter().map(|l| Some(format!("[{}]", l.join(", ")))))
    }

    /// The geometry of each row (the table's `geometry` column): GeoJSON and the numbers the page reads.
    pub fn geometry<'a, I: IntoIterator<Item = Option<Geom<'a>>>>(&mut self, v: I) -> &mut Self {
        let zone = self.zone;
        let mut gc = GeoCols::default();
        for g in v {
            let Some(g) = g else {
                gc.g.push(None);
                gc.len.push(None);
                gc.area.push(None);
                gc.bbox.push(None);
                gc.centre.push(None);
                continue;
            };
            let (json, len, area, pts): (String, f64, f64, Vec<Coord<f64>>) = match g {
                Geom::Poly(m) => {
                    let polys: Vec<String> = m.0.iter().map(|p| format!("[{}]", std::iter::once(p.exterior()).chain(p.interiors()).map(|r| ring_json(r, zone)).collect::<Vec<_>>().join(","))).collect();
                    let pts = m.0.iter().flat_map(|p| p.exterior().0.iter().copied()).collect();
                    (format!("{{\"type\":\"MultiPolygon\",\"coordinates\":[{}]}}", polys.join(",")), 0.0, geo::Area::unsigned_area(m), pts)
                }
                Geom::Line(l) => (format!("{{\"type\":\"LineString\",\"coordinates\":{}}}", ring_json(l, zone)), lines::length(l), 0.0, l.0.clone()),
                Geom::Lines(ls) => {
                    let parts: Vec<String> = ls.iter().map(|l| ring_json(l, zone)).collect();
                    (format!("{{\"type\":\"MultiLineString\",\"coordinates\":[{}]}}", parts.join(",")), ls.iter().map(lines::length).sum(), 0.0, ls.iter().flat_map(|l| l.0.iter().copied()).collect())
                }
                Geom::Point(c) => {
                    let (lon, lat) = utm_to_lonlat(c.x, c.y, zone);
                    (format!("{{\"type\":\"Point\",\"coordinates\":[{lon:.9},{lat:.9}]}}"), 0.0, 0.0, vec![c])
                }
            };
            let ll: Vec<(f64, f64)> = pts.iter().map(|c| utm_to_lonlat(c.x, c.y, zone)).collect();
            let (w, e) = ll.iter().fold((f64::INFINITY, f64::NEG_INFINITY), |a, p| (a.0.min(p.0), a.1.max(p.0)));
            let (s, nn) = ll.iter().fold((f64::INFINITY, f64::NEG_INFINITY), |a, p| (a.0.min(p.1), a.1.max(p.1)));
            gc.g.push(Some(json));
            gc.len.push(Some(len));
            gc.area.push(Some(area));
            gc.bbox.push(if ll.is_empty() { None } else { Some([w, s, e, nn]) });
            gc.centre.push(if ll.is_empty() { None } else { Some([(w + e) / 2.0, (s + nn) / 2.0]) });
        }
        self.check(gc.g.len(), "geometry");
        self.geo = Some(gc);
        self
    }

    pub fn rows(&self) -> usize {
        self.n
    }

    /// The Arrow batch of the table in the page's layout.
    pub fn batch(&self) -> RecordBatch {
        let mut fields: Vec<Field> = Vec::new();
        let mut arrays: Vec<ArrayRef> = Vec::new();
        for (name, d) in &self.cols {
            match d {
                Data::Str(v) => {
                    fields.push(Field::new(name, DataType::Utf8, true));
                    arrays.push(Arc::new(StringArray::from(v.clone())));
                }
                Data::I32(v) => {
                    fields.push(Field::new(name, DataType::Int32, true));
                    arrays.push(Arc::new(Int32Array::from(v.clone())));
                }
                Data::I64(v) => {
                    fields.push(Field::new(name, DataType::Int64, true));
                    arrays.push(Arc::new(Int64Array::from(v.clone())));
                }
                Data::F64(v) => {
                    fields.push(Field::new(name, DataType::Float64, true));
                    arrays.push(Arc::new(Float64Array::from(v.clone())));
                }
                Data::Bool(v) => {
                    fields.push(Field::new(name, DataType::Boolean, true));
                    arrays.push(Arc::new(BooleanArray::from(v.clone())));
                }
            }
        }
        if let Some(g) = &self.geo {
            let f = |name: &str, v: Vec<Option<f64>>, fields: &mut Vec<Field>, arrays: &mut Vec<ArrayRef>| {
                fields.push(Field::new(name, DataType::Float64, true));
                arrays.push(Arc::new(Float64Array::from(v)));
            };
            fields.push(Field::new("__g", DataType::Utf8, true));
            arrays.push(Arc::new(StringArray::from(g.g.clone())));
            f("__len", g.len.clone(), &mut fields, &mut arrays);
            f("__area", g.area.clone(), &mut fields, &mut arrays);
            f("__x", g.centre.iter().map(|c| c.map(|c| c[0])).collect(), &mut fields, &mut arrays);
            f("__y", g.centre.iter().map(|c| c.map(|c| c[1])).collect(), &mut fields, &mut arrays);
            f("__w", g.bbox.iter().map(|b| b.map(|b| b[0])).collect(), &mut fields, &mut arrays);
            f("__s", g.bbox.iter().map(|b| b.map(|b| b[1])).collect(), &mut fields, &mut arrays);
            f("__e", g.bbox.iter().map(|b| b.map(|b| b[2])).collect(), &mut fields, &mut arrays);
            f("__n", g.bbox.iter().map(|b| b.map(|b| b[3])).collect(), &mut fields, &mut arrays);
        }
        RecordBatch::try_new(Arc::new(Schema::new(fields)), arrays).expect("a table whose columns have one length")
    }

    /// The Parquet bytes of the table (no compression: the page's server compresses the transfer).
    pub fn parquet(&self) -> Vec<u8> {
        let batch = self.batch();
        let mut buf: Vec<u8> = Vec::new();
        let mut w = parquet::arrow::ArrowWriter::try_new(&mut buf, batch.schema(), None).expect("a Parquet writer");
        w.write(&batch).expect("a batch written");
        w.close().expect("a closed file");
        buf
    }

    pub fn write(&self, dir: &Path) -> std::io::Result<usize> {
        let bytes = self.parquet();
        std::fs::write(dir.join(format!("{}.parquet", self.name)), &bytes)?;
        Ok(bytes.len())
    }
}
