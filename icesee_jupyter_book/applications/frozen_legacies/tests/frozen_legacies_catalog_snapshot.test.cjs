const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../assets/catalog.js"), "utf8");

function harness() {
  const pending = [];
  const vectorSource = {
    features: [],
    clear() { this.features = []; },
    addFeatures(features) { this.features.push(...features); },
    getFeatureById(id) { return this.features.find(feature => feature.id === id) || null; }
  };
  class VectorLayer {
    constructor(options) { this.source = options.source; }
    getSource() { return this.source; }
    setVisible() {}
    changed() {}
  }
  const map = {
    addLayer(layer) { this.layer = layer; },
    on() {},
    getView() { return {getProjection: () => "EPSG:3857"}; }
  };
  const context = {
    URLSearchParams,
    setTimeout,
    clearTimeout,
    document: {getElementById: () => null},
    fetch(url) {
      return new Promise(resolve => pending.push({url, resolve}));
    },
    ol: {
      format: {GeoJSON: class { readFeatures(collection) { return collection.features; } }},
      source: {Vector: class { constructor() { return vectorSource; } }},
      layer: {Vector: VectorLayer},
      style: {
        Style: class {}, Stroke: class {}, Circle: class {}, Fill: class {}
      }
    }
  };
  context.window = context;
  context.FrozenLegaciesExplorerQuery = {
    normalize: query => query,
    serialize(query) {
      const params = new URLSearchParams({qv: "1"});
      for (const dataset of query.dataset || []) params.append("dataset", dataset);
      return params.toString();
    }
  };
  vm.runInNewContext(source, context, {filename: "catalog.js"});
  context.FrozenLegaciesCatalog.initializeMap({map, onChange() {}, onSelection() {}});
  return {api: context.FrozenLegaciesCatalog, map, pending, vectorSource};
}

function response(body) {
  return {ok: true, json: async () => body};
}

function snapshot(id) {
  return {
    snapshot: id,
    total: 1,
    items: [{catalog_id: id, filename: `${id}.tiff`}],
    features: {type: "FeatureCollection", features: [{id}]},
    page: {next_cursor: null},
    limits: {features_truncated: false}
  };
}

async function settle() {
  await new Promise(resolve => setImmediate(resolve));
  await new Promise(resolve => setImmediate(resolve));
}

test("one ExplorerQueryV1 response drives catalog coverage and ignores stale replies", async () => {
  const {api, pending, vectorSource} = harness();

  api.applyExplorerQuery({dataset: ["older"]});
  api.applyExplorerQuery({dataset: ["newer"]});
  assert.equal(pending.length, 2);
  assert.match(pending[0].url, /^\/frozen-legacies\/api\/radar\/explorer\?/);
  assert.match(pending[0].url, /dataset=older/);
  assert.match(pending[1].url, /dataset=newer/);

  pending[1].resolve(response(snapshot("newer")));
  await settle();
  assert.deepEqual(vectorSource.features.map(feature => feature.id), ["newer"]);

  pending[0].resolve(response(snapshot("older")));
  await settle();
  assert.deepEqual(vectorSource.features.map(feature => feature.id), ["newer"]);
});
