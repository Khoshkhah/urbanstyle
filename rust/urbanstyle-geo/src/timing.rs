//! A timer for development: `URBANSTYLE_TIMING=1` prints the time of each part to stderr. In the browser (no `Instant` there) the time
//! comes from the page (`now_ms`, `performance.now()`), and each lap goes to a log that the page reads (`take_log`).
pub struct Lap {
    t: f64,
    #[cfg(not(target_arch = "wasm32"))]
    c: u64,
    #[allow(dead_code)]
    prefix: &'static str,
}

#[cfg(target_arch = "wasm32")]
#[link(wasm_import_module = "env")]
extern "C" {
    /// The page's `performance.now()`, in milliseconds.
    fn now_ms() -> f64;
}

/// Seconds from a fixed start: natively from the first call, in the browser from the page's start.
pub fn now_s() -> f64 {
    #[cfg(target_arch = "wasm32")]
    {
        unsafe { now_ms() / 1000.0 }
    }
    #[cfg(not(target_arch = "wasm32"))]
    {
        static START: std::sync::OnceLock<std::time::Instant> = std::sync::OnceLock::new();
        START.get_or_init(std::time::Instant::now).elapsed().as_secs_f64()
    }
}

#[cfg(target_arch = "wasm32")]
static LOG: std::sync::Mutex<Vec<String>> = std::sync::Mutex::new(Vec::new());

/// The laps logged since the last call (the browser only; natively they go to stderr).
pub fn take_log() -> Vec<String> {
    #[cfg(target_arch = "wasm32")]
    {
        std::mem::take(&mut *LOG.lock().unwrap())
    }
    #[cfg(not(target_arch = "wasm32"))]
    {
        Vec::new()
    }
}

impl Lap {
    pub fn new(prefix: &'static str) -> Self {
        Lap {
            t: now_s(),
            #[cfg(not(target_arch = "wasm32"))]
            c: cpu_ns(),
            prefix,
        }
    }

    pub fn lap(&mut self, label: &str) {
        #[cfg(target_arch = "wasm32")]
        LOG.lock().unwrap().push(format!("{}: {label} {:.0} ms", self.prefix, (now_s() - self.t) * 1000.0));
        #[cfg(not(target_arch = "wasm32"))]
        if std::env::var("URBANSTYLE_TIMING").is_ok() {
            // (URBANSTYLE_TIMING=cpu: the CPU time of this thread, which a busy machine does not stretch)
            let ms = if std::env::var("URBANSTYLE_TIMING").as_deref() == Ok("cpu") { (cpu_ns() - self.c) as f64 / 1e6 } else { (now_s() - self.t) * 1000.0 };
            eprintln!("  {}: {label} {:.0} ms", self.prefix, ms);
        }
        self.t = now_s();
        #[cfg(not(target_arch = "wasm32"))]
        {
            self.c = cpu_ns();
        }
    }
}

/// The nanoseconds this thread has run on a CPU (Linux: the first field of `/proc/thread-self/schedstat`); 0 elsewhere.
#[cfg(not(target_arch = "wasm32"))]
fn cpu_ns() -> u64 {
    std::fs::read_to_string("/proc/thread-self/schedstat").ok().and_then(|s| s.split_whitespace().next().and_then(|x| x.parse().ok())).unwrap_or(0)
}
