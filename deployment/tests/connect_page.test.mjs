/*
 * Phase-3 unit tests for the manifest-driven /connect/ page logic.
 * Run with:  node --test deployment/tests/connect_page.test.mjs
 * (Also exercised from pytest via test_connect_page.py.)
 */
import test from "node:test";
import assert from "node:assert/strict";

import {
  PLATFORMS,
  validateManifest,
  detectPlatformKey,
  recommendation,
  classifyConnection,
  resolveReturnTarget,
  downloadUrl,
  humanSize,
  shortSha,
  isSha256,
  INSTALL_STEPS,
} from "../deploy_web_nginx/web/connect/connect.js";

const SHA_A = "a".repeat(64);
const SHA_B = "b".repeat(64);
const SHA_C = "c".repeat(64);

function manifest(artifacts) {
  return { schema: "cryostack.connector.manifest", version: 1, artifacts };
}

const LINUX = {
  filename: "CryoStack-Connector-linux-x86_64.tar.gz",
  sha256: SHA_A,
  size_bytes: 383220894,
  built_at: "2026-08-31T18:11:00Z",
};
const MAC_ARM = {
  filename: "CryoStack-Connector-macos-arm64.dmg",
  sha256: SHA_B,
  size_bytes: 61365713,
  built_at: "2026-08-31T18:11:00Z",
};
const WIN = {
  filename: "CryoStack-Connector-windows-x86_64.exe",
  sha256: SHA_C,
  size_bytes: 55000000,
  built_at: "2026-09-15T10:00:00Z",
};

// ── manifest: Linux only ────────────────────────────────────────────────
test("Linux-only manifest yields exactly the Linux artifact", () => {
  const v = validateManifest(manifest({ "linux-x86_64": LINUX }));
  assert.equal(v.ok, true);
  assert.deepEqual(v.artifacts.map((a) => a.key), ["linux-x86_64"]);
  assert.equal(v.artifacts[0].url, "/downloads/connectors/CryoStack-Connector-linux-x86_64.tar.gz");
  assert.equal(v.artifacts[0].os, "linux");
  assert.match(v.artifacts[0].sizeText, /MB$/);
});

// ── manifest: Linux + macOS ────────────────────────────────────────────
test("Linux+macOS manifest yields exactly those two, in display order", () => {
  const v = validateManifest(manifest({ "macos-arm64": MAC_ARM, "linux-x86_64": LINUX }));
  assert.equal(v.ok, true);
  assert.deepEqual(v.artifacts.map((a) => a.key), ["linux-x86_64", "macos-arm64"]);
});

// ── manifest: Linux + macOS + Windows (auto-appears) ───────────────────
test("Windows appears automatically once published, no code change", () => {
  const v = validateManifest(
    manifest({ "linux-x86_64": LINUX, "macos-arm64": MAC_ARM, "windows-x86_64": WIN }),
  );
  assert.deepEqual(v.artifacts.map((a) => a.key), [
    "linux-x86_64",
    "macos-arm64",
    "windows-x86_64",
  ]);
  const win = v.artifacts.find((a) => a.key === "windows-x86_64");
  assert.equal(win.os, "windows");
  assert.ok(INSTALL_STEPS.windows.length > 0);
});

// ── malformed / zero-byte / unknown entries are dropped ───────────────
test("zero-byte, malformed-sha, unknown-key and non-canonical entries are rejected", () => {
  const v = validateManifest(manifest({
    "linux-x86_64": LINUX,
    "macos-arm64": { ...MAC_ARM, size_bytes: 0 },
    "macos-x86_64": { ...MAC_ARM, filename: "CryoStack-Connector-macos-x86_64.dmg", sha256: "nothex" },
    "linux-arm64": { filename: "CryoStack-Connector-linux-arm64.tar.gz", sha256: SHA_C, size_bytes: 10 },
    "windows-x86_64": { ...WIN, filename: "totally-wrong-name.exe" },
  }));
  assert.deepEqual(v.artifacts.map((a) => a.key), ["linux-x86_64"]);
  assert.ok(v.errors.length >= 4);
});

// ── manifest unavailable / malformed ─────────────────────────────────
test("manifest unavailable or malformed -> not ok, no artifacts", () => {
  assert.equal(validateManifest(null).ok, false);
  assert.equal(validateManifest("nope").ok, false);
  assert.equal(validateManifest({}).ok, false);
  assert.equal(validateManifest({ artifacts: [] }).ok, false);
  assert.equal(validateManifest(manifest({})).ok, false);
});

// ── platform detection + recommendation ──────────────────────────────
test("detectPlatformKey maps common navigators", () => {
  assert.equal(detectPlatformKey({ userAgent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)", uaData: { architecture: "arm" } }), "macos-arm64");
  assert.equal(detectPlatformKey({ userAgent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)" }), "macos-x86_64");
  assert.equal(detectPlatformKey({ userAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64)" }), "windows-x86_64");
  assert.equal(detectPlatformKey({ userAgent: "Mozilla/5.0 (X11; Linux x86_64)" }), "linux-x86_64");
  assert.equal(detectPlatformKey({ userAgent: "some weird bot" }), null);
});

test("recommendation: detected platform published -> match", () => {
  const r = recommendation("linux-x86_64", ["linux-x86_64", "macos-arm64"]);
  assert.equal(r.state, "match");
  assert.equal(r.key, "linux-x86_64");
});

test("recommendation: Windows detected but only Linux/macOS published -> unavailable", () => {
  const r = recommendation("windows-x86_64", ["linux-x86_64", "macos-arm64"]);
  assert.equal(r.state, "unavailable");
  assert.equal(r.os, "windows");
  assert.equal(r.key, null);
});

test("recommendation: same OS different arch -> other-arch", () => {
  const r = recommendation("macos-x86_64", ["macos-arm64", "linux-x86_64"]);
  assert.equal(r.state, "other-arch");
  assert.equal(r.key, "macos-arm64");
});

test("recommendation: undetectable platform -> unknown", () => {
  assert.equal(recommendation(null, ["linux-x86_64"]).state, "unknown");
});

// ── connection state ────────────────────────────────────────────────
test("classifyConnection: no session", () => {
  assert.equal(classifyConnection({ session: null }).state, "no-session");
});

test("classifyConnection: relay unreachable is never 'connected'", () => {
  assert.equal(
    classifyConnection({ session: "abc", relayError: true, statusResp: { online: true } }).state,
    "relay-unavailable",
  );
});

test("classifyConnection: online -> connected", () => {
  assert.equal(
    classifyConnection({ session: "abc", statusResp: { online: true }, latestResp: { ok: true, session_id: "abc" } }).state,
    "connected",
  );
});

test("classifyConnection: newer session supersedes this link", () => {
  assert.equal(
    classifyConnection({ session: "abc", statusResp: { online: false }, latestResp: { ok: true, session_id: "xyz" } }).state,
    "superseded",
  );
});

test("classifyConnection: waiting when offline and still the latest", () => {
  assert.equal(
    classifyConnection({ session: "abc", statusResp: { online: false }, latestResp: { ok: true, session_id: "abc" } }).state,
    "waiting",
  );
});

// ── return target safety (no open redirect) ─────────────────────────
test("resolveReturnTarget only accepts the allowlist, defaults to CryoLauncher", () => {
  assert.deepEqual(resolveReturnTarget("icesee"), { url: "/icesee-gui/", label: "ICESEE" });
  assert.deepEqual(resolveReturnTarget("icesheets"), { url: "/icesheets/", label: "CryoLauncher" });
  assert.deepEqual(resolveReturnTarget(null), { url: "/icesheets/", label: "CryoLauncher" });
  assert.deepEqual(resolveReturnTarget("https://evil.example.com"), { url: "/icesheets/", label: "CryoLauncher" });
  assert.deepEqual(resolveReturnTarget("//evil.example.com"), { url: "/icesheets/", label: "CryoLauncher" });
});

// ── static download URLs carry no session ──────────────────────────
test("downloadUrl is static and never carries a session token", () => {
  const url = downloadUrl(PLATFORMS["linux-x86_64"].filename);
  assert.equal(url, "/downloads/connectors/CryoStack-Connector-linux-x86_64.tar.gz");
  assert.ok(!url.includes("?"));
  assert.ok(!url.includes("session"));

  const v = validateManifest(manifest({ "linux-x86_64": LINUX, "macos-arm64": MAC_ARM }));
  for (const a of v.artifacts) {
    assert.ok(!a.url.includes("?") && !a.url.toLowerCase().includes("session"));
  }
});

// ── small helpers ─────────────────────────────────────────────────
test("humanSize / shortSha / isSha256", () => {
  assert.equal(humanSize(0), "");
  assert.equal(humanSize(-5), "");
  assert.equal(humanSize(512), "512 B");
  assert.equal(humanSize(383220894), "365 MB");
  assert.equal(shortSha(SHA_A), "aaaaaaaaaaaa");
  assert.equal(shortSha("short"), "");
  assert.equal(isSha256(SHA_A), true);
  assert.equal(isSha256("xyz"), false);
});
