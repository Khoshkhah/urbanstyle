// The Explore panel's /api/ in the browser, for the dashboard on a web site with no server (urbanstyle publish;
// docs/design/online-dashboard.md): DuckDB-WASM on the area's Parquet files for Find and Filter, the tree and the focus made at publish
// time, and the AI agent on Gemini, called from the browser. The same answers as serve.py, from the same SQL.
import * as duckdb from 'https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@1.29.0/+esm';

const CFG = window.XP_STATIC_CFG, D = CFG.data;
const HID = ['__g', '__len', '__area', '__x', '__y', '__w', '__s', '__e', '__n'], KIND = ['type', 'class', 'kind', 'use'], NAME = ['name', 'road'];
const NUM = ['DOUBLE', 'FLOAT', 'INTEGER', 'BIGINT'];
const store = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); if (v) localStorage.setItem(k, v); else localStorage.removeItem(k) } catch (e) { return null } };
const json = u => fetch(D + u).then(r => { if (!r.ok) throw new Error(u + ': ' + r.status); return r.json() });
const lit = v => "'" + String(v).replace(/'/g, "''") + "'";
const r1 = x => Math.round((x || 0) * 10) / 10;
// (an id past 2**53, a BIGINT hash: as text, as the server's JSON would round it otherwise)
const val = v => typeof v === 'bigint' ? (v >= -9007199254740991n && v <= 9007199254740991n ? Number(v) : String(v)) : v;
let meta, tree, focusAll, conn;

async function start() {
  [meta, tree, focusAll] = await Promise.all([json('meta.json'), json('tree.json'), json('focus.json')]);
  const b = await duckdb.selectBundle(duckdb.getJsDelivrBundles());
  const worker = new Worker(URL.createObjectURL(new Blob([`importScripts("${b.mainWorker}");`], { type: 'text/javascript' })));
  const db = new duckdb.AsyncDuckDB(new duckdb.ConsoleLogger(duckdb.LogLevel.WARNING), worker);
  await db.instantiate(b.mainModule, b.pthreadWorker);
  conn = await db.connect();
  await conn.query('CREATE SCHEMA space');
  const base = new URL(D, location.href).href;
  for (const [t, f] of Object.entries(meta.files)) {
    await db.registerFileURL(f, base + f, duckdb.DuckDBDataProtocol.HTTP, false);
    await conn.query(`CREATE TABLE space."${t}" AS SELECT * FROM read_parquet('${f}')`);
  }
}

async function rows(sql) {
  const r = await conn.query(sql);
  return r.toArray().map(x => { const o = x.toJSON(); for (const k in o) o[k] = val(o[k]); return o });
}

// the rows of sql as GeoJSON features with their totals (serve.Area.features)
async function features(sql, layer, limit = meta.row_limit) {
  const q = `SELECT * FROM (${sql}) WHERE __g IS NOT NULL`;
  const [t] = await rows(`SELECT count(*) AS n, sum(__len) AS l, sum(__area) AS a FROM (${q})`);
  const idc = layer && meta.panel[layer] ? meta.panel[layer].id : null, kinds = {}, feats = [];
  for (const p of await rows(`${q} LIMIT ${limit}`)) {
    const g = JSON.parse(p.__g), ln = p.__len, ar = p.__area;
    HID.forEach(k => delete p[k]);
    const fid = idc ? p[idc] : ['id', 'part_id', 'object_id', 'source_id', 'unit_id'].map(k => p[k]).find(v => v);
    const lab = [KIND.map(k => p[k]).find(v => v), NAME.map(k => p[k]).find(v => v)].filter(Boolean).join(' · ') || layer || '';
    const ty = p.type || p.class || p.kind || '';
    kinds[ty] = (kinds[ty] || 0) + 1;
    feats.push({ type: 'Feature', geometry: g, properties: { ...p, _id: fid ?? null, _label: lab, _layer: layer || '', _m: r1(ln), _m2: r1(ar) } });
  }
  return { type: 'FeatureCollection', features: feats, total: Number(t.n), length_m: r1(t.l), area_m2: r1(t.a),
    kinds: Object.entries(kinds).sort((a, b) => b[1] - a[1]), sql };
}

// one layer's rows that meet every condition, in bbox if given (serve.Area.query)
async function query(layer, where, bbox) {
  const L = meta.panel[layer];
  if (!L) throw new Error('no layer ' + layer);
  const cols = Object.fromEntries(L.cols), conds = L.base ? [L.base] : [];
  for (const { field: c, op, value: v } of where) {
    if (!(c in cols)) throw new Error(`no field ${c} in ${layer}`);
    const num = NUM.includes(cols[c]), s = `CAST("${c}" AS VARCHAR)`, o = op === '!=' ? '<>' : op;
    if (op === 'contains') conds.push(`${s} ILIKE ${lit('%' + v + '%')}`);
    else if (op === 'in') conds.push(`${s} IN (${(v || []).map(lit).join(', ') || 'NULL'})`);
    else if (['=', '!=', '>=', '<='].includes(op)) conds.push(num ? `"${c}" ${o} ${Number(v)}` : `${s} ${o} ${lit(v)}`);
    else throw new Error('no operator ' + op);
  }
  if (bbox) conds.push(`__e >= ${+bbox[0]} AND __w <= ${+bbox[2]} AND __n >= ${+bbox[1]} AND __s <= ${+bbox[3]}`);
  return features(`SELECT * FROM ${L.table}` + (conds.length ? ' WHERE ' + conds.join(' AND ') : ''), layer);
}

// names, ids, types and OSM references that hold q, in every layer (serve.Area.search)
async function search(q, per = 50) {
  const out = { type: 'FeatureCollection', features: [], total: 0, length_m: 0, area_m2: 0, kinds: [], sql: null }, kinds = {};
  for (const [name, L] of Object.entries(meta.panel)) {
    const cs = L.cols.filter(([c, ty]) => (c === L.id || meta.search_cols.includes(c)) && ty === 'VARCHAR').map(([c]) => c);
    if (!cs.length || !meta.files[L.table.split('.')[1]]) continue;
    const r = await features(`SELECT * FROM ${L.table} WHERE (${cs.map(c => `"${c}" ILIKE ${lit('%' + q + '%')}`).join(' OR ')})` +
      (L.base ? ` AND ${L.base}` : ''), name, per);
    if (r.total) { out.features.push(...r.features); out.total += r.total; out.length_m += r.length_m; out.area_m2 += r.area_m2; kinds[name] = r.total }
  }
  out.kinds = Object.entries(kinds).sort((a, b) => b[1] - a[1]);
  return out;
}

// a street space's or a block's focus, made at publish time; several spaces: all their buildings and objects
function focus(layer, id) {
  const F = focusAll[layer] || {};
  if (layer !== 'Street spaces') return F[id] || null;
  const ids = String(id).split(',').filter(Boolean), blds = new Set(), objs = new Set();
  ids.forEach(u => { const f = F[u]; if (f) { f.blds.forEach(x => blds.add(x)); f.objs.forEach(x => objs.add(x)) } });
  return { units: ids, blds: [...blds].sort(), objs: [...objs] };
}

// the agent (serve.Agent on Gemini): run_sql and show_on_map on the browser's tables
const NOT_READ_ONLY = /\b(attach|detach|copy|install|load|pragma|create|insert|update|delete|drop|alter|export|import|call|set|checkpoint|vacuum)\b|\bread_\w+|\bglob\s*\(|\bst_read\w*|\bsniff_csv/i;
function readOnly(sql) {
  const s = sql.trim().replace(/;\s*$/, '').trim();
  if (s.includes(';')) throw new Error('one statement only');
  if (!/^\s*(select|with)\b/i.test(s)) throw new Error('only SELECT or WITH');
  if (NOT_READ_ONLY.test(s.replace(/'[^']*'/g, "''"))) throw new Error('this query writes, loads or reads files: not allowed');
  return s;
}
async function runSql(sql) {
  const rs = await rows(`SELECT * FROM (${readOnly(sql)}) LIMIT ${meta.sql_rows + 1}`);
  rs.forEach(r => { if (typeof r.__g === 'string') r.__g = r.__g.slice(0, 120) });
  return JSON.stringify({ rows: rs.slice(0, meta.sql_rows), more_rows: rs.length > meta.sql_rows });
}
async function tool(name, a, run) {
  if (name === 'run_sql') { run.queries.push({ sql: a.sql }); return runSql(a.sql) }
  if (name === 'show_on_map') {
    run.queries.push({ sql: a.sql, title: a.title, map: true });
    const s = await features(readOnly(a.sql));
    s.title = a.title; run.map = s;
    return JSON.stringify({ shown: s.features.length, total: s.total, length_m: s.length_m, area_m2: s.area_m2, kinds: s.kinds.slice(0, 10) });
  }
  throw new Error('no tool ' + name);
}
const TOOLS = [{ functionDeclarations: [
  { name: 'run_sql', description: "Run one read-only DuckDB query (SELECT or WITH) on the area's tables. Returns at most 200 rows as JSON; " +
      'leave __g (the shape) out unless you need it.',
    parameters: { type: 'object', properties: { sql: { type: 'string', description: 'One SELECT or WITH statement.' } }, required: ['sql'] } },
  { name: 'show_on_map', description: "Show the rows of a query on the planner's map (2D and 3D) and in the results list, with their " +
      'totals. The query must return the column __g, and should return an id and a name or type. Returns the count, total length and area.',
    parameters: { type: 'object', properties: { sql: { type: 'string', description: 'One SELECT or WITH statement that returns __g.' },
      title: { type: 'string', description: 'A few words that say what is shown.' } }, required: ['sql', 'title'] } }] }];
let hist = [];
const used = new Set();        // (models whose day is used up)
const keyOf = () => store('xp-gemini-key') || (CFG.gemini.startsWith('__') ? '' : CFG.gemini);
async function gen(model, key, body) {
  const r = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent`,
    { method: 'POST', headers: { 'Content-Type': 'application/json', 'x-goog-api-key': key }, body: JSON.stringify(body) });
  const t = await r.json().catch(() => ({}));
  if (!r.ok) { const e = new Error((t.error && t.error.message) || r.statusText); e.status = r.status; e.body = JSON.stringify(t); throw e }
  return t;
}
async function ask(question) {
  const key = keyOf(), fresh = hist.length === 0, run = { queries: [], map: null };
  const out = answer => ({ answer, queries: run.queries, map: run.map, fresh });
  if (!key) return out('Ask needs a Gemini API key: click "Your own Gemini key" below.');
  const order = meta.gemini_models;
  let model = order.find(m => !used.has(m)) || order[0], text = '';
  const start = hist.length;
  hist.push({ role: 'user', parts: [{ text: question }] });
  for (let turn = 0; turn < meta.turns; turn++) {
    const body = { systemInstruction: { parts: [{ text: meta.system }] }, contents: hist, tools: TOOLS,
      ...(turn === meta.turns - 1 ? { toolConfig: { functionCallingConfig: { mode: 'NONE' } } } : {}) };   // (the last step: an answer)
    let r = null, waits = 0;
    const tried = new Set();
    while (true) {
      try { r = await gen(model, key, body); break } catch (e) {
        const msg = e.message + ' ' + (e.body || ''), st = e.status;
        const day = (st === 429 && /PerDay|limit: 0/.test(msg)) || st === 404, busy = st === 503;
        if (day) used.add(model);
        else if (busy) tried.add(model);
        else if (st === 429 && waits < 3) {        // (the per-minute limit: wait as asked, the same model)
          waits++;
          const m = /retry in ([0-9.]+)s/.exec(msg) || /"retryDelay":\s*"([0-9.]+)s"/.exec(msg);
          await new Promise(z => setTimeout(z, Math.min(m ? +m[1] * 1000 + 1000 : 10000, 60000)));
          continue;
        }
        const next = order.find(m => !used.has(m) && !tried.has(m));
        if ((day || busy) && next) { model = next; continue }
        hist.length = start;
        if (st === 400 || st === 403) return out(`Gemini did not accept the key (${st}): ${e.message.slice(0, 200)}`);
        if (day) return out("Gemini's free daily quota is used up for every model this page can use. Ask again tomorrow, or click " +
          '"Your own Gemini key" below.');
        if (busy) return out('Every Gemini model is overloaded just now. Ask again in a minute.');
        return out('The Gemini API gave an error: ' + msg.slice(0, 300));
      }
    }
    const cand = (r.candidates || [])[0];
    if (!cand || !cand.content) return out(`Gemini gave no answer (${cand ? cand.finishReason : JSON.stringify(r.promptFeedback || {})}).`);
    hist.push(cand.content);         // (the model's whole turn, with its thought signatures)
    const parts = cand.content.parts || [];
    text = parts.filter(p => p.text && !p.thought).map(p => p.text).join('\n').trim();
    const calls = parts.filter(p => p.functionCall).map(p => p.functionCall);
    if (!calls.length) break;
    const replies = [];
    for (const fc of calls) {
      let res;
      try { res = { result: await tool(fc.name, fc.args || {}, run) } } catch (e) { res = { error: String(e.message || e) } }
      replies.push({ functionResponse: { name: fc.name, response: res } });
    }
    hist.push({ role: 'user', parts: replies });
  }
  return out(text || '(no answer: the question needed more steps than allowed)');
}

async function api(u, b) {
  const url = new URL(u, location.href), p = url.pathname.replace(/^.*\/api\//, ''), q = url.searchParams;
  try {
    if (!b) {
      if (p === 'meta') return { area: meta.area, layers: meta.layers, levels: meta.levels, street_levels: meta.street_levels, agent: true };
      if (p === 'tree') return tree[q.get('node') || ''] || [];
      if (p === 'search') return await search(q.get('q') || '');
      if (p === 'focus') return focus(q.get('layer') || '', q.get('id') || '');
    } else {
      if (p === 'focus') return focus(b.layer || 'Street spaces', (b.ids || []).join(','));
      if (p === 'query') return await query(b.layer, b.where || [], b.bbox);
      if (p === 'ask') return await ask(b.question);
      if (p === 'forget') { hist = []; return { ok: true } }
    }
  } catch (e) { return { error: String(e.message || e) } }
  return { error: 'no such api: ' + p };
}

// the Ask tab: the visitor's own Gemini key (kept in this browser only), and the data's sources
function extras() {
  const box = document.getElementById('xp-a');
  if (!box) return;
  box.insertAdjacentHTML('beforeend', '<div class=xprow style="justify-content:space-between;font-size:11px;color:#64748b">' +
    '<span>Data: © OpenStreetMap contributors (ODbL) and the city\'s open data.</span><button class=xplink id=xpkey>Your own Gemini key</button></div>');
  document.getElementById('xpkey').onclick = () => {
    const k = prompt('Your Gemini API key (from aistudio.google.com). It stays in this browser only. Empty: use the page\'s key.', store('xp-gemini-key') || '');
    if (k !== null) store('xp-gemini-key', k.trim());
  };
}

start().then(() => { extras(); window.XP_STATIC_RESOLVE(api) })
  .catch(e => { console.error('urbanstyle: the data did not load', e); window.XP_STATIC_RESOLVE(() => Promise.reject(e)) });
