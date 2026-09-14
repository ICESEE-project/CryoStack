/*
 * CryoStack Connector -- /connect/ onboarding + pairing page logic.
 *
 * Everything user-visible about which platforms exist is driven entirely by
 * /downloads/connectors/manifest.json. Publishing a new platform (for
 * example Windows) into that manifest makes it appear here with no change
 * to this file.
 *
 * Pure, DOM-free functions are exported for unit testing under Node. The DOM
 * controller (initConnectPage) is only ever invoked from index.html in a
 * browser, so importing this module in Node never touches window/document.
 */

export const MANIFEST_SCHEMA = "cryostack.connector.manifest";
export const DOWNLOAD_BASE = "/downloads/connectors/";
export const MANIFEST_URL = DOWNLOAD_BASE + "manifest.json";
export const RELAY_BASE = "/connector";

// The canonical platforms CryoStack can publish, keyed by the manifest's
// platform key. Declaration order here is the display order. Adding a key
// here (with its canonical filename) is all that a brand-new platform needs.
export const PLATFORMS = {
  "linux-x86_64": {
    os: "linux", label: "Linux", sublabel: "x86_64", icon: "\u{1F427}",
    filename: "CryoStack-Connector-linux-x86_64.tar.gz",
  },
  "macos-arm64": {
    os: "macos", label: "macOS", sublabel: "Apple Silicon", icon: "\u{1F34E}",
    filename: "CryoStack-Connector-macos-arm64.dmg",
  },
  "macos-x86_64": {
    os: "macos", label: "macOS", sublabel: "Intel", icon: "\u{1F34E}",
    filename: "CryoStack-Connector-macos-x86_64.dmg",
  },
  "windows-x86_64": {
    os: "windows", label: "Windows", sublabel: "x86_64", icon: "\u{25A6}",
    filename: "CryoStack-Connector-windows-x86_64.exe",
  },
};

export const PLATFORM_ORDER = Object.keys(PLATFORMS);

export const OS_LABEL = { linux: "Linux", macos: "macOS", windows: "Windows" };

// Install steps are selected by platform *identity*, never by filename, and
// reflect the real packaging: linux = a .tar.gz holding a single onefile
// binary; macOS = an unsigned .app inside a .dmg; windows = a onefile .exe.
export const INSTALL_STEPS = {
  linux: [
    "Download the Linux x86_64 archive below.",
    "Extract it:  tar -xzf CryoStack-Connector-linux-x86_64.tar.gz",
    "Run the connector:  ./CryoStack-Connector",
    "Leave it running, and keep your campus VPN connected.",
  ],
  macos: [
    "Download the .dmg below and double-click it to mount “CryoStack Connector”.",
    "Drag CryoStack-Connector.app into your Applications folder.",
    "First launch only: right-click the app and choose Open, then confirm. The app is not yet notarized, so a plain double-click is blocked the first time — this is the normal macOS route and does not disable Gatekeeper.",
    "The connector then runs in the menu bar. Leave it running, and keep your campus VPN connected.",
  ],
  windows: [
    "Download CryoStack-Connector-windows-x86_64.exe below.",
    "Run it. If Windows SmartScreen appears, choose More info → Run anyway.",
    "The connector runs in the system tray. Leave it running, and keep your campus VPN connected.",
  ],
};

// Safe return targets. A ?app= value is only ever mapped through this table;
// an arbitrary URL is never accepted (no open redirect).
export const RETURN_TARGETS = {
  icesheets: { url: "/icesheets/", label: "CryoLauncher" },
  icesee: { url: "/icesee-gui/", label: "ICESEE" },
};

export function resolveReturnTarget(appParam) {
  return RETURN_TARGETS[appParam] || RETURN_TARGETS.icesheets;
}

const HEX64 = /^[0-9a-f]{64}$/i;

export function isSha256(value) {
  return typeof value === "string" && HEX64.test(value);
}

export function shortSha(sha) {
  return isSha256(sha) ? sha.slice(0, 12) : "";
}

export function humanSize(bytes) {
  const n0 = Number(bytes);
  if (!Number.isFinite(n0) || n0 <= 0) return "";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let n = n0;
  let i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i += 1;
  }
  const val = i === 0
    ? String(Math.round(n))
    : n < 10 ? n.toFixed(1) : String(Math.round(n));
  return `${val} ${units[i]}`;
}

// Static, session-free download URL. A pairing token is NEVER appended here.
export function downloadUrl(filename) {
  return DOWNLOAD_BASE + filename;
}

/*
 * Validate a parsed manifest.json. Returns:
 *   { artifacts: [ {key, os, label, sublabel, icon, filename, sha256,
 *                   shortSha, sizeBytes, sizeText, builtAt, url} ],
 *     errors: [string],
 *     ok: boolean }
 *
 * Only canonical, well-formed entries survive: a known platform key, the
 * canonical filename for that key, a 64-hex sha256 and size_bytes > 0.
 * Anything else is dropped and recorded in `errors` (never rendered).
 */
export function validateManifest(raw) {
  const errors = [];
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return { artifacts: [], errors: ["manifest is missing or not an object"], ok: false };
  }
  if (raw.schema && raw.schema !== MANIFEST_SCHEMA) {
    errors.push(`unexpected manifest schema: ${String(raw.schema)}`);
  }
  const entries = raw.artifacts;
  if (!entries || typeof entries !== "object" || Array.isArray(entries)) {
    return {
      artifacts: [],
      errors: [...errors, "manifest has no artifacts object"],
      ok: false,
    };
  }

  const artifacts = [];
  for (const key of Object.keys(entries)) {
    const meta = PLATFORMS[key];
    if (!meta) {
      errors.push(`unknown platform key: ${key}`);
      continue;
    }
    const entry = entries[key] || {};
    const filename = entry.filename;
    if (typeof filename !== "string" || !filename) {
      errors.push(`${key}: missing filename`);
      continue;
    }
    if (filename !== meta.filename) {
      errors.push(`${key}: non-canonical filename ${filename}`);
      continue;
    }
    if (!isSha256(entry.sha256)) {
      errors.push(`${key}: missing or malformed sha256`);
      continue;
    }
    const sizeBytes = Number(entry.size_bytes);
    if (!Number.isFinite(sizeBytes) || sizeBytes <= 0) {
      errors.push(`${key}: size_bytes must be > 0`);
      continue;
    }
    artifacts.push({
      key,
      os: meta.os,
      label: meta.label,
      sublabel: meta.sublabel,
      icon: meta.icon,
      filename,
      sha256: entry.sha256.toLowerCase(),
      shortSha: shortSha(entry.sha256),
      sizeBytes,
      sizeText: humanSize(sizeBytes),
      builtAt: typeof entry.built_at === "string" ? entry.built_at : "",
      url: downloadUrl(filename),
    });
  }
  artifacts.sort(
    (a, b) => PLATFORM_ORDER.indexOf(a.key) - PLATFORM_ORDER.indexOf(b.key),
  );
  return { artifacts, errors, ok: artifacts.length > 0 };
}

/*
 * Best-guess platform key from navigator-ish info. Returns a canonical key
 * or null. This is only ever used as a recommendation.
 */
export function detectPlatformKey(nav = {}) {
  const ua = String(nav.userAgent || "").toLowerCase();
  const plat = String(nav.platform || "").toLowerCase();
  const uaArch = String((nav.uaData && nav.uaData.architecture) || "").toLowerCase();
  const hay = `${ua} ${plat}`;
  const isArm =
    uaArch.includes("arm") || hay.includes("aarch64") || hay.includes("arm64");

  if (hay.includes("mac")) return isArm ? "macos-arm64" : "macos-x86_64";
  if (hay.includes("win")) return "windows-x86_64";
  if (hay.includes("linux") || hay.includes("x11")) return "linux-x86_64";
  return null;
}

/*
 * Given the detected key and the set of *available* keys (from the
 * validated manifest), decide what to recommend. Never invents a download.
 *   state "match"       -> detected platform is published (key set)
 *   state "other-arch"  -> same OS is published, different arch (key set)
 *   state "unavailable" -> detected OS not published at all
 *   state "unknown"     -> could not detect the platform
 */
export function recommendation(detectedKey, availableKeys) {
  const available = new Set(availableKeys || []);
  if (detectedKey && available.has(detectedKey)) {
    return { state: "match", key: detectedKey, os: PLATFORMS[detectedKey].os };
  }
  const os =
    detectedKey && PLATFORMS[detectedKey] ? PLATFORMS[detectedKey].os : null;
  if (os) {
    const sameOs = [...available].filter(
      (k) => PLATFORMS[k] && PLATFORMS[k].os === os,
    );
    if (sameOs.length) return { state: "other-arch", key: sameOs[0], os };
    return { state: "unavailable", key: null, os };
  }
  return { state: "unknown", key: null, os: null };
}

/*
 * Classify the live pairing state from the relay's coarse status response.
 *   inputs: { session, statusResp, relayError }
 *   statusResp = GET /connector/status/<session>
 *              -> { online: bool, state: "waiting"|"connected"|"disconnected"
 *                                        |"superseded"|"expired"|"unknown" } | null
 *
 * The relay no longer exposes a global "latest session" endpoint, so staleness
 * is read straight from `state`. Never reports "connected" when the relay
 * could not be reached.
 */
export function classifyConnection({ session, statusResp, relayError } = {}) {
  if (!session) return { state: "no-session" };
  if (relayError || !statusResp) return { state: "relay-unavailable" };
  const s = statusResp.state;
  if (statusResp.online === true || s === "connected") return { state: "connected" };
  if (s === "superseded") return { state: "superseded" };
  if (s === "expired") return { state: "expired" };
  if (s === "unknown") return { state: "session-unknown" };
  return { state: "waiting" };
}

export const CONNECTION_TEXT = {
  "no-session": {
    tone: "neutral",
    title: "No pairing session",
    detail:
      "Open this page from CryoLauncher or ICESEE so it can create a connector session for you.",
  },
  "relay-unavailable": {
    tone: "error",
    title: "Can’t reach the CryoStack relay",
    detail:
      "The relay service is not responding. If you are running CryoStack yourself, start it with: deployment/services.sh start-connector",
  },
  superseded: {
    tone: "error",
    title: "This pairing link is out of date",
    detail:
      "A newer connector session has been created. Return to the application and open Connector Setup again for a fresh link and pairing code.",
  },
  expired: {
    tone: "error",
    title: "This pairing session has expired",
    detail:
      "Return to the application and open Connector Setup again for a fresh pairing code.",
  },
  "session-unknown": {
    tone: "error",
    title: "This pairing session was not found",
    detail:
      "The link may be old, or the relay may have restarted. Open Connector Setup again from the application.",
  },
  connected: {
    tone: "ok",
    title: "Connected ✓",
    detail: "CryoStack Connector is online. You can return to your application.",
  },
  waiting: {
    tone: "wait",
    title: "Waiting for CryoStack Connector…",
    detail:
      "Launch CryoStack Connector on your computer. It pairs with this session automatically.",
  },
};

/* ===================================================================== *
 *  DOM controller -- browser only.                                       *
 * ===================================================================== */

function isBrowser() {
  return typeof window !== "undefined" && typeof document !== "undefined";
}

function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[c]));
}

async function fetchJSON(url) {
  const resp = await fetch(url, { cache: "no-store" });
  if (!resp.ok) throw new Error(`${url} -> HTTP ${resp.status}`);
  return resp.json();
}

function artifactCard(a, recommended) {
  const steps = (INSTALL_STEPS[a.os] || [])
    .map((s) => `<li>${esc(s)}</li>`)
    .join("");
  return el(`
    <article class="dl-card${recommended ? " is-recommended" : ""}">
      ${recommended ? '<p class="dl-flag">Recommended for this computer</p>' : ""}
      <div class="dl-head">
        <span class="dl-icon" aria-hidden="true">${esc(a.icon || "\u{1F4E6}")}</span>
        <div class="dl-title">
          <h3>${esc(a.label)}</h3>
          <p class="dl-sub">${esc(a.sublabel)} &middot; CryoStack Connector</p>
        </div>
      </div>
      <dl class="dl-meta">
        <div><dt>Size</dt><dd>${esc(a.sizeText || "—")}</dd></div>
        <div>
          <dt>SHA-256</dt>
          <dd class="sha-row">
            <code class="sha" title="${esc(a.sha256)}">${esc(a.shortSha)}…</code>
            <button type="button" class="copy" data-copy="${esc(a.sha256)}">Copy checksum</button>
          </dd>
        </div>
      </dl>
      <a class="btn" href="${esc(a.url)}" download>Download</a>
      <details class="dl-steps">
        <summary>Install steps for ${esc(OS_LABEL[a.os] || a.label)}</summary>
        <ol>${steps}</ol>
      </details>
    </article>
  `);
}

function renderDownloads(root, view, detectedKey) {
  root.innerHTML = "";

  if (!view.ok) {
    root.appendChild(el(`
      <div class="notice error">
        <b>No connector downloads are available right now.</b>
        <p>The download manifest could not be read or contained no valid
        artifacts. Please try again shortly, or browse
        <a href="${esc(DOWNLOAD_BASE)}">${esc(DOWNLOAD_BASE)}</a> directly.</p>
      </div>
    `));
    return;
  }

  const availableKeys = view.artifacts.map((a) => a.key);
  const rec = recommendation(detectedKey, availableKeys);

  const banner =
    rec.state === "match"
      ? `Detected <b>${esc(PLATFORMS[rec.key].label)} ${esc(PLATFORMS[rec.key].sublabel)}</b> — the recommended download is highlighted below.`
      : rec.state === "other-arch"
        ? `Detected <b>${esc(OS_LABEL[rec.os])}</b>, but not that exact architecture. The closest published build is highlighted; all downloads are listed.`
        : rec.state === "unavailable"
          ? `A <b>${esc(OS_LABEL[rec.os])}</b> connector is not currently published. Available downloads are listed below.`
          : `Could not detect your platform. All available downloads are listed below.`;

  root.appendChild(el(`<p class="dl-banner">${banner}</p>`));

  const grid = el('<div class="dl-grid"></div>');
  for (const a of view.artifacts) {
    grid.appendChild(artifactCard(a, a.key === rec.key));
  }
  root.appendChild(grid);
}

function paintConnection(box, state, returnTarget) {
  const info = CONNECTION_TEXT[state] || CONNECTION_TEXT.waiting;
  box.dataset.tone = info.tone;
  box.querySelector(".conn-title").textContent = info.title;
  box.querySelector(".conn-detail").textContent = info.detail;

  const ret = box.querySelector(".conn-return");
  if (state === "connected") {
    ret.hidden = false;
    ret.innerHTML =
      `<a class="btn" href="${esc(returnTarget.url)}">Return to ${esc(returnTarget.label)}</a>`;
  } else {
    ret.hidden = true;
    ret.innerHTML = "";
  }
}

function startPairing(session, returnTarget) {
  const box = document.getElementById("conn");
  const statusUrl = `${RELAY_BASE}/status/${encodeURIComponent(session)}`;

  async function tick() {
    let statusResp = null;
    let relayError = false;
    try {
      statusResp = await fetchJSON(statusUrl);
    } catch (_e) {
      relayError = true;
    }
    const { state } = classifyConnection({ session, statusResp, relayError });
    paintConnection(box, state, returnTarget);
  }

  tick();
  return window.setInterval(tick, 2500);
}

function wireCopyButtons() {
  document.addEventListener("click", async (ev) => {
    const btn = ev.target.closest("button.copy");
    if (!btn) return;
    const value = btn.dataset.copy || "";
    try {
      await navigator.clipboard.writeText(value);
      const prev = btn.textContent;
      btn.textContent = "Copied ✓";
      window.setTimeout(() => {
        btn.textContent = prev;
      }, 1600);
    } catch (_e) {
      btn.textContent = "Copy failed";
    }
  });
}

export async function initConnectPage() {
  if (!isBrowser()) return;

  const params = new URLSearchParams(window.location.search);
  // The "session" query parameter (v2) is the NON-SECRET session identifier.
  // Used here only for live status polling (GET /connector/status/<id>) and as
  // a diagnostic reference. The pairing capability is the one-time pairing code
  // shown in the CryoLauncher / ICESEE UI -- never in a URL -- and there is no
  // global "newest session" discovery.
  const session = params.get("session");
  const returnTarget = resolveReturnTarget(params.get("app"));

  wireCopyButtons();

  // ---- pairing panel -------------------------------------------------
  const pairBox = document.getElementById("pair");
  if (session) {
    pairBox.querySelector(".pair-code").textContent = session;
    pairBox.querySelector("button.copy").dataset.copy = session;
    pairBox.hidden = false;
    document.getElementById("pair-missing").hidden = true;
  } else {
    pairBox.hidden = true;
    document.getElementById("pair-missing").hidden = false;
  }

  // ---- connection status -------------------------------------------
  paintConnection(
    document.getElementById("conn"),
    session ? "waiting" : "no-session",
    returnTarget,
  );
  if (session) startPairing(session, returnTarget);

  // ---- downloads (manifest-driven) --------------------------------
  const dlRoot = document.getElementById("downloads");
  const detectedKey = detectPlatformKey({
    userAgent: navigator.userAgent,
    platform: navigator.platform,
    uaData: navigator.userAgentData,
  });
  try {
    const raw = await fetchJSON(MANIFEST_URL);
    renderDownloads(dlRoot, validateManifest(raw), detectedKey);
  } catch (_e) {
    renderDownloads(dlRoot, { artifacts: [], errors: ["manifest fetch failed"], ok: false }, detectedKey);
  }
}
