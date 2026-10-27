/*
 * dash-shim.js
 * Implementación mínima de la API `dash` (data, calc, onData, colors…) para que el
 * dashboard corra como página estática en GitHub Pages, leyendo los JSON de ./data/.
 */
(function () {
  const DATASETS = ['reels', 'followers', 'm_metrics', 'm_importance', 'm_local', 'm_predictions', 'm_coefs'];
  const store = {};      // id -> {status, data, message}
  const calcs = {};      // id -> {inputs, fn}
  const listeners = [];
  let params = {};

  DATASETS.forEach((id) => (store[id] = { status: 'loading', data: [] }));

  function computeCalc(id, seen = new Set()) {
    const c = calcs[id];
    if (seen.has(id)) return { status: 'error', data: [], message: 'ciclo' };
    seen.add(id);
    const ins = c.inputs.map((i) => (calcs[i] ? computeCalc(i, seen) : store[i] || { status: 'missing', data: [] }));
    const bad = ins.find((x) => x.status !== 'ok');
    if (bad) return { status: bad.status, data: [] };
    if (c.cache && c.cacheKey === c.inputs.map((i) => (calcs[i] ? calcs[i].version : store[i].version)).join('|')) return c.cache;
    let res;
    try { res = { status: 'ok', data: c.fn(...ins.map((x) => x.data)) }; }
    catch (e) { console.error('calc', id, e); res = { status: 'error', data: [], message: String(e) }; }
    c.cacheKey = c.inputs.map((i) => (calcs[i] ? calcs[i].version : store[i].version)).join('|');
    c.cache = res;
    c.version = (c.version || 0) + 1;
    return res;
  }

  function fire() {
    listeners.forEach((fn) => { try { fn(); } catch (e) { console.error(e); } });
  }

  const colors = ['var(--series-1)', 'var(--series-2)', 'var(--series-3)', 'var(--series-4)',
    'var(--series-5)', 'var(--series-6)', 'var(--series-7)', 'var(--series-8)'];

  window.dash = {
    data(id) {
      if (calcs[id]) { const r = computeCalc(id); return { ...r, refreshing: false, meta: [] }; }
      const s = store[id] || { status: 'missing', data: [] };
      return { ...s, refreshing: false, meta: [], columns: s.data && s.data[0] ? Object.keys(s.data[0]) : [] };
    },
    calc(id, def) { calcs[id] = { inputs: def.inputs, fn: def.fn }; },
    loader() {},
    onData(fn) { listeners.push(fn); try { fn(); } catch (e) { console.error(e); } },
    colors,
    refresh() {},
    params: () => ({ ...params }),
    setParams(p) { params = { ...params, ...p }; fire(); },
    resetParams() { params = {}; fire(); },
    setLink(name) { try { history.replaceState(null, '', '#' + name); } catch (e) { /* noop */ } },
  };

  let resizeTimer;
  window.addEventListener('resize', () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(fire, 150); });

  window.addEventListener('DOMContentLoaded', () => {
    DATASETS.forEach((id) => {
      fetch(`data/${id}.json?v=${Date.now()}`)
        .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then((rows) => { store[id] = { status: 'ok', data: rows, version: Date.now() + Math.random() }; fire(); })
        .catch((e) => { store[id] = { status: 'error', data: [], message: String(e), version: Math.random() }; fire(); });
    });
  });
})();
