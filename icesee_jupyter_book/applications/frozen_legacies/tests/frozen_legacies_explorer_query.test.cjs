const test = require("node:test");
const assert = require("node:assert/strict");
const Q = require("../assets/explorer_query.js");

test("canonical query is stable, sorted, deduplicated and round trips", () => {
  const query = Q.normalize({dataset: ["zeta", "alpha", "alpha"], flight: ["127"], cbd_min: 471, cbd_max: 483});
  assert.equal(Q.serialize(query), "qv=1&dataset=alpha&dataset=zeta&flight=127&cbd_min=471&cbd_max=483");
  assert.deepEqual(Q.parse({hash: `#${Q.serialize(query)}`, search: ""}), query);
});

test("legacy query links remain readable and invalid ranges fail closed", () => {
  assert.deepEqual(Q.parse({hash: "", search: "?ds=spri&flight=127"}).dataset, ["spri"]);
  const invalid = Q.normalize({cbd_min: 500, cbd_max: 400});
  assert.equal(invalid.cbd_min, undefined);
  assert.equal(invalid.cbd_max, undefined);
});

test("store suppresses equivalent updates and clear preserves audience", () => {
  const store = Q.createStore({dataset: ["spri"], audience: "published"});
  let calls = 0;
  store.subscribe(() => calls++);
  store.set({dataset: ["spri", "spri"]});
  assert.equal(calls, 0);
  store.clear();
  assert.equal(calls, 1);
  assert.equal(store.get().audience, "published");
  assert.deepEqual(store.get().dataset, undefined);
});

test("replace makes back-forward state authoritative rather than merging", () => {
  const store = Q.createStore({dataset: ["spri"], flight: ["127"], q: "film"});
  store.replace({dataset: ["other"]});
  assert.deepEqual(store.get().dataset, ["other"]);
  assert.equal(store.get().flight, undefined);
  assert.equal(store.get().q, undefined);
});
