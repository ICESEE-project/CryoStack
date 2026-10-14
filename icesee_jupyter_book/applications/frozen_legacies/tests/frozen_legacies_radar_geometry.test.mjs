/*
 * Unit tests for the Frozen Legacies radar viewing geometry
 * (assets/radar_geometry.js). Pure functions only.
 *
 * Run with:  node --test frozen_legacies_radar_geometry.test.mjs
 * (Also exercised from pytest via test_frozen_legacies_radar_frontend.py.)
 */
import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const G = require("../assets/radar_geometry.js");

// Reference strip: F127-C0471_C0483.tiff is 37943 x 2400.
const W = 37943;
const H = 2400;

test("fit scale: smallest scale whose full height fits", () => {
  assert.equal(G.fitScale(H, 2400), 1);
  assert.equal(G.fitScale(H, 600), 4);
  assert.equal(G.fitScale(H, 599), 8);
  assert.equal(G.fitScale(H, 10), 64);
});

test("min scale keeps a full-width view under the output limit", () => {
  assert.equal(G.minScale(1000, H), 1);        // 1000 x 2400 = 2.4M
  assert.equal(G.minScale(3000, H), 2);        // 3000 x 2400 = 7.2M > 6M
  assert.equal(G.clampScale(1, 3000, H), 2);
  assert.equal(G.clampScale(3, 1000, H), 1);   // invalid -> lowest valid
});

test("window width follows the viewer and never exceeds the image", () => {
  assert.equal(G.windowWidth(1000, 4, W), 4000);
  assert.equal(G.windowWidth(1000, 64, W), W);
  assert.equal(G.windowWidth(0, 1, W), 1);
});

test("positions clamp to the strip", () => {
  assert.equal(G.clampX(-50, 4000, W), 0);
  assert.equal(G.clampX(W, 4000, W), W - 4000);
  assert.equal(G.shiftX(0, 0.1, 4000, W), 400);
  assert.equal(G.shiftX(0, -1, 4000, W), 0);
  assert.equal(G.shiftX(30000, 1, 4000, W), W - 4000);
});

test("zoom keeps the centre column", () => {
  const x = G.zoomAround(10000, 4000, 2000, W);
  assert.equal(x + 1000, 12000);
  assert.equal(G.nextScale(4, -1), 2);
  assert.equal(G.nextScale(4, 1), 8);
  assert.equal(G.nextScale(1, -1), 1);
  assert.equal(G.nextScale(64, 1), 64);
});

test("overview scale fits the target width", () => {
  assert.equal(G.overviewScale(W, 1600), 32);   // 1186 px wide
  assert.equal(G.overviewScale(800, 1600), 1);
});

test("visual CBD estimate is linear over the filename range and bounded", () => {
  assert.equal(G.estimateViewCbd(0, W, 471, 483), 471);
  assert.equal(G.estimateViewCbd(W - 1, W, 471, 483), 483);
  assert.equal(G.estimateViewCbd((W - 1) / 2, W, 471, 483), 477);
  assert.equal(G.estimateViewCbd(10 * W, W, 471, 483), 483);
  assert.equal(G.estimateViewCbd(100, W, null, 483), null);
});

test("navigation lookup is exact (no interpolation)", () => {
  const rows = [{ cbd: 471, lat: -81.4 }, { cbd: 473, lat: -81.5 }];
  assert.equal(G.navForCbd(rows, 471).lat, -81.4);
  assert.equal(G.navForCbd(rows, 472), null);
  assert.equal(G.navForCbd(rows, null), null);
});

test("shared sources link to a selection only when they name its dataset", () => {
  const sources = [
    { key: "f127", dataset_id: null, flight: "127", observation_tiff: null },
    { key: "lyra-125", dataset_id: "lyra", flight: "125", observation_tiff: null },
    { key: "lyra-tiff", dataset_id: "lyra", flight: "125", observation_tiff: "a.tiff" }
  ];
  const keys = sel => G.matchSources(sources, sel).map(s => s.key);
  assert.deepEqual(keys({ datasetId: "lyra", flight: 125, tiff: "a.tiff" }), ["lyra-125", "lyra-tiff"]);
  assert.deepEqual(keys({ datasetId: "lyra", flight: "125", tiff: "b.tiff" }), ["lyra-125"]);
  assert.deepEqual(keys({ datasetId: "lyra", flight: "141", tiff: null }), []);
  assert.deepEqual(keys({ datasetId: null, flight: "127", tiff: null }), []);   // F127 never linked
  assert.deepEqual(G.matchSources(sources, null), []);
});

test("view URLs carry only the server asset id and integers", () => {
  assert.equal(
    G.viewUrl("0".repeat(32), 10, 400, 4),
    `/frozen-legacies/api/assets/${"0".repeat(32)}/view?x=10&width=400&scale=4`
  );
});

test("ASTRA click -> matplotlib data coordinates of the working window", () => {
  const rect = { left: 100, top: 50, width: 1150, height: 775 };   // 2300 x 1550 shown at half size
  const c = (x, y) => G.astraDataCoordinates(x, y, rect, 2300, 1550);
  assert.deepEqual(c(100, 50), { x: -0.5, y: -0.5 });              // top-left corner of pixel 0
  assert.deepEqual(c(100.25, 50.25), { x: 0, y: 0 });             // centre of pixel 0
  assert.deepEqual(c(675, 437.5), { x: 1149.5, y: 774.5 });
  assert.equal(c(1250, 300), null);                                // right edge = outside (xdata None)
  assert.equal(c(99, 300), null);
  assert.equal(c(500, 825), null);
  assert.equal(G.astraDataCoordinates(1, 1, { left: 0, top: 0, width: 0, height: 10 }, 2300, 1550), null);
});

test("ASTRA window box keeps the exact aspect ratio and fits the stage", () => {
  const stages = [[642, 470], [960, 700], [1187, 900], [1412, 952], [1946, 1400], [332, 2000], [5000, 300], [10, 10]];
  for (const [sw, sh] of stages) {
    const box = G.fitBox(sw, sh, 2300, 1550);
    assert.ok(Number.isInteger(box.width));
    assert.equal(box.height, (box.width * 1550) / 2300);           // never stretched in one direction
    assert.ok(box.width <= Math.max(100, sw));
    assert.ok(box.height <= Math.max(80, sh) + 1e-9);
  }
  assert.deepEqual(G.fitBox(1187, 900, 2300, 1550), { width: 1187, height: (1187 * 1550) / 2300 });
  assert.deepEqual(G.fitBox(2000, 620, 2300, 1550), { width: 920, height: 620 });   // height-limited
  assert.equal(G.fitBox(500, 500, 0, 1550), null);
});

test("click mapping is independent of the displayed box size (layouts, focus view, phones)", () => {
  // the same data coordinate shown at any box size maps back to itself;
  // ASTRA's int() then gives the same pixel at every size
  const points = [[0, 0], [0.25, 0.25], [199.25, 300.25], [1150.25, 774.75], [2299.25, 1549.25]];
  const sizes = [[642, 470], [920, 620], [1157, 900], [1412, 952], [1946, 1400], [331, 400]];
  for (const [x, y] of points) {
    const seen = new Set();
    for (const [sw, sh] of sizes) {
      const box = G.fitBox(sw, sh, 2300, 1550);
      const rect = { left: 37, top: 211.5, width: box.width, height: box.height };
      const cx = rect.left + ((x + 0.5) / 2300) * rect.width;
      const cy = rect.top + ((y + 0.5) / 1550) * rect.height;
      const c = G.astraDataCoordinates(cx, cy, rect, 2300, 1550);
      assert.ok(Math.abs(c.x - x) < 1e-9 && Math.abs(c.y - y) < 1e-9);
      seen.add(`${Math.trunc(c.x + 1e-9)},${Math.trunc(c.y + 1e-9)}`);
    }
    assert.equal(seen.size, 1);
  }
});
