//! The geometry helpers of urbanstyle's Rust code (docs/notes/rust-browser.md, step 1).
//!
//! They do what the Python code does with shapely: `poly`, `D`, `I`, `union_all`, `buffer`, `wide`, an index of boxes, the position of a
//! point along a line. They are thin: `geo` 0.33 (its `BooleanOps` and its `Buffer` are made on `i_overlay`) and `rstar` do the work, and
//! nothing here calls GEOS, so the crate builds for `wasm32-unknown-unknown`. A rule written with these helpers does not need
//! `make_valid`, `set_precision` or a `grid_size`: `i_overlay` returns valid polygons.

pub mod files;
pub mod index;
pub mod io;
pub mod lines;
pub mod ops;
pub mod timing;
pub mod utm;

pub use geo;
pub use timing::Lap;
pub use geo::{Coord, LineString, MultiPolygon, Point, Polygon, Rect};
