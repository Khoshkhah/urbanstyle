// Loads urbanstyle.wasm and the files of files.json, puts each file into the module, runs the chain and posts the result.
let mem, panicText = "";
const text = (p, n) => new TextDecoder().decode(new Uint8Array(mem.buffer, p, n));
onmessage = async (e) => {
  try {
    const t0 = performance.now();
    postMessage({ status: "Loading the module and the files ..." });
    const { instance } = await WebAssembly.instantiateStreaming(fetch("urbanstyle.wasm"), {
      env: { now_ms: () => performance.now(), log_text: (p, n) => { panicText = text(p, n); } },
    });
    const x = instance.exports;
    mem = x.memory;
    const files = await (await fetch("files.json")).json();
    for (const f of files) {
      const data = new Uint8Array(await (await fetch(f)).arrayBuffer());
      const name = new TextEncoder().encode("/" + f);
      const np = x.alloc(name.length);
      new Uint8Array(mem.buffer, np, name.length).set(name);
      const dp = x.alloc(data.length);
      new Uint8Array(mem.buffer, dp, data.length).set(data);
      x.put_file(np, name.length, dp, data.length);
    }
    const load_s = (performance.now() - t0) / 1000;
    postMessage({ status: `Running the chain on ${files.length} files ...` });
    let n;
    try { n = x.run(e.data.checks); } catch (err) { throw new Error((panicText || String(err))); }
    const result = JSON.parse(text(x.result_ptr(), n));
    postMessage({ result, load_s, memory_mb: Math.round(mem.buffer.byteLength / 1048576) });
  } catch (err) {
    postMessage({ error: panicText || String(err) });
  }
};
