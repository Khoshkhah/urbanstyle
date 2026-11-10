//! A Parquet file read whole, with typed accessors by column name. The files are SimReady's (golden files, DuckDB's Parquet, Snappy) and
//! duckOSM's. A column the file does not have reads as all null, so one reader serves the files that hold several tables (`table` column).
use arrow_array::*;
use bytes::Bytes;
use parquet::arrow::arrow_reader::ParquetRecordBatchReaderBuilder;
use std::path::Path;

pub struct Table {
    batches: Vec<RecordBatch>,
}

fn err<E: std::fmt::Display>(e: E) -> String {
    e.to_string()
}

fn is<T: 'static>(a: &dyn Array) -> Option<&T> {
    a.as_any().downcast_ref::<T>()
}

impl Table {
    pub fn from_bytes(b: Bytes) -> Result<Table, String> {
        let reader = ParquetRecordBatchReaderBuilder::try_new(b).map_err(err)?.with_batch_size(16384).build().map_err(err)?;
        Ok(Table { batches: reader.collect::<Result<Vec<_>, _>>().map_err(err)? })
    }

    pub fn open(path: &Path) -> Result<Table, String> {
        Table::from_bytes(Bytes::from(std::fs::read(path).map_err(|e| format!("{}: {e}", path.display()))?))
    }

    pub fn rows(&self) -> usize {
        self.batches.iter().map(|b| b.num_rows()).sum()
    }

    fn gather<T>(&self, name: &str, f: impl Fn(&dyn Array, usize) -> Option<T>) -> Vec<Option<T>> {
        let mut out = Vec::with_capacity(self.rows());
        for b in &self.batches {
            match b.column_by_name(name) {
                Some(c) => out.extend((0..b.num_rows()).map(|i| if c.is_null(i) { None } else { f(c.as_ref(), i) })),
                None => out.extend((0..b.num_rows()).map(|_| None)),
            }
        }
        out
    }

    pub fn i64s(&self, name: &str) -> Vec<Option<i64>> {
        self.gather(name, |a, i| is::<Int64Array>(a).map(|x| x.value(i)).or_else(|| is::<Int32Array>(a).map(|x| x.value(i) as i64)))
    }

    pub fn f64s(&self, name: &str) -> Vec<Option<f64>> {
        self.gather(name, |a, i| is::<Float64Array>(a).map(|x| x.value(i)).or_else(|| is::<Float32Array>(a).map(|x| x.value(i) as f64)))
    }

    pub fn bools(&self, name: &str) -> Vec<Option<bool>> {
        self.gather(name, |a, i| is::<BooleanArray>(a).map(|x| x.value(i)))
    }

    /// A `MAP(VARCHAR, VARCHAR)` column (OSM's tags): a list of key and value entries.
    pub fn map_strs(&self, name: &str) -> Vec<Option<std::collections::BTreeMap<String, String>>> {
        self.gather(name, |a, i| {
            let m = is::<MapArray>(a)?;
            let (keys, values) = (m.keys(), m.values());
            let r = m.value_offsets();
            Some((r[i] as usize..r[i + 1] as usize).filter_map(|j| Some((str_at(keys.as_ref(), j)?, str_at(values.as_ref(), j)?))).collect())
        })
    }

    pub fn strs(&self, name: &str) -> Vec<Option<String>> {
        self.gather(name, |a, i| str_at(a, i))
    }

    pub fn blobs(&self, name: &str) -> Vec<Option<Vec<u8>>> {
        self.gather(name, |a, i| {
            is::<BinaryArray>(a)
                .map(|x| x.value(i).to_vec())
                .or_else(|| is::<LargeBinaryArray>(a).map(|x| x.value(i).to_vec()))
                .or_else(|| is::<BinaryViewArray>(a).map(|x| x.value(i).to_vec()))
        })
    }

    fn lists<T>(&self, name: &str, f: impl Fn(&dyn Array, usize) -> Option<T>) -> Vec<Option<Vec<T>>> {
        self.gather(name, |a, i| {
            let inner: ArrayRef = match is::<ListArray>(a) {
                Some(l) => l.value(i),
                None => is::<LargeListArray>(a)?.value(i),
            };
            Some((0..inner.len()).filter(|&j| !inner.is_null(j)).filter_map(|j| f(inner.as_ref(), j)).collect())
        })
    }

    pub fn list_i64s(&self, name: &str) -> Vec<Option<Vec<i64>>> {
        self.lists(name, |a, j| is::<Int64Array>(a).map(|x| x.value(j)).or_else(|| is::<Int32Array>(a).map(|x| x.value(j) as i64)))
    }

    pub fn list_strs(&self, name: &str) -> Vec<Option<Vec<String>>> {
        self.lists(name, |a, j| str_at(a, j))
    }
}

fn str_at(a: &dyn Array, i: usize) -> Option<String> {
    is::<StringArray>(a)
        .map(|x| x.value(i).to_string())
        .or_else(|| is::<LargeStringArray>(a).map(|x| x.value(i).to_string()))
        .or_else(|| is::<StringViewArray>(a).map(|x| x.value(i).to_string()))
}
