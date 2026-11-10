//! Readers of the raw inputs as tables (Parquet), in place of the JSON fixtures that the Python exporters wrote. `table` reads a Parquet
//! file, `wkb` its geometry columns, `boundary` the area, `division` and `blocks` make the inputs of those steps from SimReady's files
//! and duckOSM's edges.
pub mod blocks;
pub mod boundary;
pub mod division;
pub mod features;
pub mod ground;
pub mod proj;
pub mod osm;
pub mod streets;
pub mod table;
pub mod wkb;
