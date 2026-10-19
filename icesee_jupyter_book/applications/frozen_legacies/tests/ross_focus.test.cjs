const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

class MultiLineString {
  constructor(coordinates) { this.coordinates = coordinates; }
  getType() { return "MultiLineString"; }
  getCoordinates() { return this.coordinates; }
}

class Feature {
  constructor(geometry, values = {}) { this.geometry = geometry; this.values = {...values}; }
  getGeometry() { return this.geometry; }
  setGeometry(geometry) { this.geometry = geometry; }
  set(key, value) { this.values[key] = value; }
  clone() { return new Feature(this.geometry, this.values); }
}

const square = {
  getType: () => "Polygon",
  getCoordinates: () => [[[-1, -1], [1, -1], [1, 1], [-1, 1], [-1, -1]]],
  intersectsCoordinate: ([x, y]) => x >= -1 && x <= 1 && y >= -1 && y <= 1
};
const context = {window: {}, ol: {geom: {MultiLineString}}};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, "../assets/ross_focus.js"), "utf8"), context);

const flight = new Feature({
  getType: () => "LineString",
  getCoordinates: () => [[-2, 0], [2, 0]]
});
const inside = new Feature({getCoordinates: () => [0, 0]});
const outside = new Feature({getCoordinates: () => [2, 2]});
const result = context.window.FrozenLegaciesRossFocus.focus({
  flightFeatures: [flight],
  observationFeatures: [inside, outside],
  boundaryFeature: new Feature(square)
});

assert.equal(result.flights.length, 1);
assert.deepEqual(JSON.parse(JSON.stringify(result.flights[0].getGeometry().getCoordinates())), [[[-1, 0], [1, 0]]]);
assert.deepEqual(result.observations, [inside]);
assert.equal(result.flights[0].values.display_region, "Ross Ice Shelf");
assert.equal(inside.values.display_region, "Ross Ice Shelf");
console.log("Ross focus clipping tests passed");
