/* Canonical, shareable Frozen Legacies explorer state (ExplorerQueryV1). */
(function (root) {
  "use strict";

  const MULTI = ["dataset", "flight", "source", "product", "review"];
  const ORDER = ["qv", "audience", ...MULTI, "cbd_min", "cbd_max", "q", "sort"];
  const SAFE = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;

  function values(params, key) {
    return [...new Set(params.getAll(key).map(value => value.trim()).filter(value => SAFE.test(value)))]
      .sort((a, b) => a.localeCompare(b, "en", { numeric: true }));
  }

  function normalize(input = {}) {
    const query = { qv: "1", audience: input.audience === "published" ? "published" : "workspace" };
    for (const key of MULTI) {
      const list = Array.isArray(input[key]) ? input[key] : (input[key] ? [input[key]] : []);
      const clean = [...new Set(list.map(String).map(value => value.trim()).filter(value => SAFE.test(value)))]
        .sort((a, b) => a.localeCompare(b, "en", { numeric: true }));
      if (clean.length) query[key] = clean;
    }
    for (const key of ["cbd_min", "cbd_max"]) {
      if (input[key] !== "" && input[key] !== null && input[key] !== undefined) {
        const number = Number(input[key]);
        if (Number.isFinite(number) && number >= 0) query[key] = String(number);
      }
    }
    if (query.cbd_min && query.cbd_max && Number(query.cbd_min) > Number(query.cbd_max)) {
      delete query.cbd_min;
      delete query.cbd_max;
    }
    const text = String(input.q || "").trim().slice(0, 100);
    if (text) query.q = text;
    if (["flight_cbd", "acquired", "released", "relevance"].includes(input.sort)) query.sort = input.sort;
    return Object.freeze(query);
  }

  function parse(locationLike) {
    const hash = new URLSearchParams(String(locationLike?.hash || "").replace(/^#/, ""));
    const legacy = new URLSearchParams(String(locationLike?.search || "").replace(/^\?/, ""));
    const params = hash.has("qv") || hash.has("dataset") || hash.has("ds") ? hash : legacy;
    const raw = {};
    for (const key of MULTI) raw[key] = values(params, key);
    if (!raw.dataset.length) raw.dataset = values(params, "ds");
    for (const key of ["audience", "cbd_min", "cbd_max", "q", "sort"]) raw[key] = params.get(key) || "";
    return normalize(raw);
  }

  function serialize(query) {
    const normalized = normalize(query);
    const params = new URLSearchParams();
    for (const key of ORDER) {
      const value = normalized[key];
      if (!value || (key === "audience" && value === "workspace")) continue;
      for (const item of Array.isArray(value) ? value : [value]) params.append(key, item);
    }
    if (!params.has("qv")) params.set("qv", "1");
    return params.toString();
  }

  function createStore(initial) {
    let query = normalize(initial);
    const listeners = new Set();
    return Object.freeze({
      get: () => query,
      subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
      set(patch) {
        const next = normalize({ ...query, ...patch });
        if (serialize(next) === serialize(query)) return query;
        query = next;
        listeners.forEach(listener => listener(query));
        return query;
      },
      replace(value) {
        const next = normalize(value);
        if (serialize(next) === serialize(query)) return query;
        query = next;
        listeners.forEach(listener => listener(query));
        return query;
      },
      clear() { return this.set({ dataset: [], flight: [], source: [], product: [], review: [], cbd_min: "", cbd_max: "", q: "", sort: "" }); }
    });
  }

  root.FrozenLegaciesExplorerQuery = Object.freeze({ normalize, parse, serialize, createStore });
  if (typeof module !== "undefined") module.exports = root.FrozenLegaciesExplorerQuery;
})(typeof window === "undefined" ? globalThis : window);
