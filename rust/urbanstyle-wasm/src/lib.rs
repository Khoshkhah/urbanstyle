//! The whole build in the browser, with no `wasm-bindgen`: plain exported functions on the module's memory. The page (`rust/www/`)
//! calls `alloc` and `put_file` for each input file, then `run`, then reads the result (JSON) at `result_ptr`, `run`'s value bytes long.
//! The module imports `env.now_ms` (`performance.now()`) and `env.log_text` (a text the module writes: the panic message).
use std::path::Path;
use std::sync::Mutex;

#[cfg(target_arch = "wasm32")]
#[link(wasm_import_module = "env")]
extern "C" {
    fn log_text(ptr: *const u8, len: usize);
}

static RESULT: Mutex<Vec<u8>> = Mutex::new(Vec::new());

/// Room for `len` bytes, which the page fills and gives back to `put_file`.
#[no_mangle]
pub extern "C" fn alloc(len: usize) -> *mut u8 {
    let mut v = Vec::<u8>::with_capacity(len);
    let p = v.as_mut_ptr();
    std::mem::forget(v);
    p
}

/// Keep the file `name` (UTF-8, `name_len` bytes) with its `data_len` bytes; both were made by `alloc`, and the module owns them now.
///
/// # Safety
/// Both pointers come from `alloc` with these lengths, and the page does not use them again.
#[no_mangle]
pub unsafe extern "C" fn put_file(name: *mut u8, name_len: usize, data: *mut u8, data_len: usize) {
    let name = String::from_utf8(Vec::from_raw_parts(name, name_len, name_len)).expect("a UTF-8 file name");
    urbanstyle_geo::files::put(&name, Vec::from_raw_parts(data, data_len, data_len));
}

/// Run the chain on the files under `/in/` (`fixtures/monaco-*-fixture.json`, `simready/`, `pass0/`, `features/`); `checks` 1 runs the
/// checks too. The value is the length of the result: `{"steps": [[name, seconds]], "laps": [...], "counts": {...}, "checks": [...]}`.
#[no_mangle]
pub extern "C" fn run(checks: i32) -> usize {
    #[cfg(target_arch = "wasm32")]
    std::panic::set_hook(Box::new(|p| {
        let s = p.to_string();
        unsafe { log_text(s.as_ptr(), s.len()) }
    }));
    let sources = urbanstyle_build::Sources { simready: "/in/simready".into(), pass0: "/in/pass0".into(), features: Some("/in/features".into()) };
    let start = urbanstyle_geo::timing::now_s();
    let b = urbanstyle_build::run(Path::new("/in/fixtures"), "monaco-", None, checks == 1, Some(&sources));
    let all = urbanstyle_geo::timing::now_s() - start;
    let out = serde_json::json!({
        "steps": b.timings,
        "all": all,
        "laps": urbanstyle_geo::timing::take_log(),
        "counts": {
            "spaces": b.model.spaces.len(), "parts": b.model.parts.len(), "marks": b.model.marks.len(), "ground": b.model.ground.len(),
            "surfaces": b.surfaces.len(), "stretches": b.model.stretches.len(), "elements": b.elements.len(), "objects": b.objects.len(),
            "things": b.things.len(), "registry": b.registry.len(),
        },
        "checks": b.checks.iter().map(|c| format!("{} {} {}", c.id, c.status(), c.count)).collect::<Vec<_>>(),
    });
    let mut r = RESULT.lock().unwrap();
    *r = serde_json::to_vec(&out).unwrap();
    r.len()
}

/// Where the result of the last `run` is.
#[no_mangle]
pub extern "C" fn result_ptr() -> *const u8 {
    RESULT.lock().unwrap().as_ptr()
}
