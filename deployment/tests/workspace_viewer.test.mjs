/*
 * Unit tests for the Workspace Run Log / Results viewer geometry + live-tail
 * follow logic. Pure functions only -- the DOM bootstrap is skipped here
 * because `document` is undefined under `node --test`.
 *
 * Run with:  node --test deployment/tests/workspace_viewer.test.mjs
 * (Also exercised from pytest via test_workspace_viewer_js.py.)
 */
import test from "node:test";
import assert from "node:assert/strict";

import {
  computeViewerMaxHeight,
  nextTailState,
} from "../../cryostack_src/frontend/cryolauncher/workspace/viewer_geometry.js";

// ── sizing ────────────────────────────────────────────────────────────────
test("short content: no cap when the viewer fits the viewport", () => {
  // caller passes the *content* height decision to CSS; this function only
  // yields a ceiling. A generous viewport still yields a (large) ceiling, and
  // CSS `overflow-y:auto` means short content never scrolls.
  const px = computeViewerMaxHeight({ viewerTop: 200, viewportHeight: 1000 });
  assert.ok(px > 700 && px <= 800);
});

test("long viewport space is the main practical ceiling", () => {
  const px = computeViewerMaxHeight({ viewerTop: 150, viewportHeight: 900,
    bottomPad: 24 });
  assert.equal(px, 900 - 150 - 24);
});

test("stacked / mobile: no cap (null) -> natural document flow", () => {
  assert.equal(computeViewerMaxHeight({ viewerTop: 100, viewportHeight: 800,
    narrow: true }), null);
});

test("tiny / invalid geometry -> null, never a cramped viewer", () => {
  assert.equal(computeViewerMaxHeight({ viewerTop: 780, viewportHeight: 800 }),
    null);                                            // 800-780-24 < hardMin
  assert.equal(computeViewerMaxHeight({ viewerTop: NaN, viewportHeight: 800 }),
    null);
  assert.equal(computeViewerMaxHeight({ viewerTop: 100, viewportHeight: 0 }),
    null);
});

test("left column bottom is a SECONDARY balance constraint", () => {
  // viewport would allow 900-200-24 = 676; the left column ends higher
  const px = computeViewerMaxHeight({
    viewerTop: 200, viewportHeight: 900, leftColumnBottom: 760,
  });
  assert.equal(px, 760 - 200 - 24);                   // balanced to the left col
});

test("left balance never pulls a live viewer below the useful minimum", () => {
  // a very short left column (e.g. Agent mode): left avail = 320-200-24 = 96,
  // well under liveMin -> ignored; the viewer keeps the full viewport space.
  const px = computeViewerMaxHeight({
    viewerTop: 200, viewportHeight: 1000, leftColumnBottom: 320,
  });
  assert.equal(px, 1000 - 200 - 24);
});

test("left balance is ignored when it would only make the viewer larger", () => {
  const px = computeViewerMaxHeight({
    viewerTop: 200, viewportHeight: 700, leftColumnBottom: 5000,
  });
  assert.equal(px, 700 - 200 - 24);                   // viewport still the ceiling
});

test("result is rounded to a whole px", () => {
  const px = computeViewerMaxHeight({ viewerTop: 100.4, viewportHeight: 600.6 });
  assert.equal(px, Math.round(600.6 - 100.4 - 24));
  assert.equal(px, 476);
});

test("just below hardMin of usable space -> null (retry later, stay natural)", () => {
  // 500 - 250 - 24 = 226 < hardMin (240)
  assert.equal(
    computeViewerMaxHeight({ viewerTop: 250, viewportHeight: 500 }), null);
});

test("uses visualViewport-style height verbatim (no hardcoded constant)", () => {
  const a = computeViewerMaxHeight({ viewerTop: 100, viewportHeight: 800 });
  const b = computeViewerMaxHeight({ viewerTop: 100, viewportHeight: 640 });
  assert.equal(a - b, 160);                           // tracks the viewport 1:1
});

// ── live-tail follow ─────────────────────────────────────────────────────
const scrollable = { scrollTop: 0, scrollHeight: 2000, clientHeight: 400 };
const atBottom = { scrollTop: 1600, scrollHeight: 2000, clientHeight: 400 };

test("auto-follow stays active while the user is at the bottom", () => {
  const st = nextTailState({ following: true, ...atBottom, event: "user-scroll" });
  assert.equal(st.following, true);
  assert.equal(st.showJump, false);
});

test("new content keeps the bottom in view while following", () => {
  const st = nextTailState({ following: true, ...atBottom, event: "mutation" });
  assert.equal(st.following, true);          // caller scrolls to bottom
});

test("scrolling up suspends auto-follow and shows Jump to latest", () => {
  const st = nextTailState({ following: true, ...scrollable, event: "user-scroll" });
  assert.equal(st.following, false);
  assert.equal(st.showJump, true);
});

test("new content does NOT resume follow or snap down while suspended", () => {
  const st = nextTailState({ following: false, scrollTop: 100,
    scrollHeight: 4000, clientHeight: 400, event: "mutation" });
  assert.equal(st.following, false);
  assert.equal(st.showJump, true);
});

test("Jump to latest only shows when suspended AND the viewer is scrollable", () => {
  const notScrollable = { scrollTop: 0, scrollHeight: 300, clientHeight: 400 };
  const st = nextTailState({ following: false, ...notScrollable, event: "mutation" });
  assert.equal(st.showJump, false);
});

test("clicking Jump to latest resumes follow", () => {
  const st = nextTailState({ following: false, ...scrollable, event: "jump" });
  assert.equal(st.following, true);
  assert.equal(st.showJump, false);
});

test("scrolling back to the bottom re-arms auto-follow", () => {
  const st = nextTailState({ following: false, ...atBottom, event: "user-scroll" });
  assert.equal(st.following, true);
  assert.equal(st.showJump, false);
});
