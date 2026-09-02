/*
 * CryoStack Workspace -- Run Log / Results viewer sizing + live-tail follow.
 *
 * Two pure functions (unit-tested with `node --test`) plus a DOM bootstrap that
 * only runs in the browser. The bootstrap is embedded verbatim into a Voila
 * <script> (the `export` keywords are stripped at embed time), so this file is
 * the single source of truth for both the tests and the runtime.
 *
 * Sizing priority:
 *   1. natural content height        (a short viewer ends naturally -- correct)
 *   2. useful visible viewport space (the main practical ceiling)
 *   3. desktop left-column balance   (secondary; never cramps a live viewer)
 *
 * It sets ONLY a scoped custom property on the Run Log / Results viewers:
 *   --cryostack-workspace-viewer-max-height: <px>
 * The CSS applies it as `max-height: var(--cryostack-workspace-viewer-max-height)`
 * with `overflow-y: auto`, so a viewer only scrolls once content exceeds the
 * available region. The Workspace card height is never set from JS.
 */

/**
 * The max-height (px) for a Run Log / Results viewer, or `null` for
 * "no cap -- natural document flow" (short content, stacked/mobile, or
 * temporarily-incomplete geometry: caller keeps the CSS min-height and
 * recomputes on the next layout event).
 *
 * @param {object} g
 * @param {number} g.viewerTop         viewer top, viewport-relative (px)
 * @param {number} g.viewportHeight    visible viewport height (visualViewport
 *                                     height when available, else innerHeight)
 * @param {number} [g.leftColumnBottom] left Run Settings column bottom,
 *                                     viewport-relative (px); NaN/omitted to
 *                                     skip the desktop balance constraint
 * @param {boolean} [g.narrow]         stacked / mobile layout -> always null
 * @param {number} [g.bottomPad]       breathing room below the viewer (px)
 * @param {number} [g.hardMin]         absolute floor; below this -> null
 * @param {number} [g.liveMin]         the left-column balance never pulls the
 *                                     viewer below this (a short left column
 *                                     must not cramp a live viewer)
 * @returns {number|null}
 */
export function computeViewerMaxHeight(g) {
  const {
    viewerTop,
    viewportHeight,
    leftColumnBottom = NaN,
    narrow = false,
    bottomPad = 24,
    hardMin = 240,
    liveMin = 420,
  } = g || {};

  if (narrow) return null;                       // stacked: natural page flow
  if (!Number.isFinite(viewerTop)) return null;
  if (!Number.isFinite(viewportHeight) || viewportHeight <= 0) return null;

  const top = Math.max(viewerTop, 0);
  const viewportAvail = viewportHeight - top - bottomPad;

  // tiny / invalid geometry: do NOT collapse the viewer -- keep natural flow +
  // CSS min-height, recompute on the next resize / layout event.
  if (!Number.isFinite(viewportAvail) || viewportAvail < hardMin) return null;

  let avail = viewportAvail;

  // Secondary desktop balance: if the right Workspace would otherwise run
  // substantially below the left column, pull toward the left column's bottom
  // -- but only when that still leaves a genuinely usable viewer (>= liveMin),
  // so a short left column (e.g. Agent mode) never makes a live viewer short.
  if (Number.isFinite(leftColumnBottom)) {
    const leftAvail = leftColumnBottom - top - bottomPad;
    if (leftAvail >= liveMin && leftAvail < avail) {
      avail = leftAvail;
    }
  }

  return Math.max(hardMin, Math.round(avail));
}

/**
 * Next auto-follow state for the live Run Log tail.
 *
 * @param {object} s
 * @param {boolean} s.following      current auto-follow state
 * @param {number} s.scrollTop
 * @param {number} s.scrollHeight
 * @param {number} s.clientHeight
 * @param {"mutation"|"user-scroll"|"jump"} s.event
 * @param {number} [s.nearPx]        "close enough to the bottom" tolerance
 * @returns {{following: boolean, showJump: boolean, atBottom: boolean}}
 */
export function nextTailState(s) {
  const {
    following,
    scrollTop = 0,
    scrollHeight = 0,
    clientHeight = 0,
    event,
    nearPx = 40,
  } = s || {};

  const distanceFromBottom = scrollHeight - scrollTop - clientHeight;
  const atBottom = distanceFromBottom <= nearPx;
  const scrollable = scrollHeight - clientHeight > nearPx;

  let follow = following;
  if (event === "user-scroll") {
    // scrolling up suspends follow; scrolling back to the bottom re-arms it
    follow = atBottom;
  } else if (event === "jump") {
    follow = true;
  }
  // a content mutation never changes `follow` -- the caller scrolls iff following

  return { following: follow, showJump: scrollable && !follow, atBottom };
}


// ---------------------------------------------------------------------------
// Browser bootstrap (skipped under `node --test`)
// ---------------------------------------------------------------------------
function installWorkspaceViewer() {
  const PROP = "--cryostack-workspace-viewer-max-height";
  const VIEWERS = ".cryostack-log-viewer, .cryostack-results-viewer";
  const LOG_VIEWER = ".cryostack-log-viewer";
  const LEFT = ".cryostack-left-workspace";
  const STALE = ".cryostack-right-workspace, .icesee-right";
  const NARROW = 1050;

  const releaseStale = () => document.querySelectorAll(STALE).forEach((el) => {
    el.style.removeProperty("height");
    el.style.removeProperty("min-height");
    el.style.removeProperty("max-height");
    el.style.removeProperty("overflow");
  });

  const viewportHeight = () =>
    (window.visualViewport && window.visualViewport.height) || window.innerHeight;

  let raf = 0;
  const sizeViewers = () => {
    raf = 0;
    const narrow = window.innerWidth <= NARROW;
    const leftEl = document.querySelector(LEFT);
    const leftBottom = (!narrow && leftEl)
      ? leftEl.getBoundingClientRect().bottom : NaN;
    document.querySelectorAll(VIEWERS).forEach((el) => {
      const px = computeViewerMaxHeight({
        viewerTop: el.getBoundingClientRect().top,
        viewportHeight: viewportHeight(),
        leftColumnBottom: leftBottom,
        narrow,
      });
      if (px == null) el.style.removeProperty(PROP);
      else el.style.setProperty(PROP, px + "px");
    });
  };
  const schedule = () => { if (!raf) raf = requestAnimationFrame(sizeViewers); };

  // --- live-tail auto-follow (Run Log only) -------------------------------
  const wireTail = (viewer) => {
    if (viewer.dataset.cryoTail === "1") return;
    viewer.dataset.cryoTail = "1";
    const state = { following: true };
    const scroller = viewer;                 // the .cryostack-log-viewer scrolls

    const jump = document.createElement("button");
    jump.type = "button";
    jump.className = "cryostack-tail-jump";
    jump.textContent = "Jump to latest ↓";
    jump.hidden = true;
    viewer.appendChild(jump);

    let programmatic = false;
    const toBottom = () => {
      programmatic = true;
      scroller.scrollTop = scroller.scrollHeight;
      requestAnimationFrame(() => { programmatic = false; });
    };
    const apply = (st) => {
      state.following = st.following;
      jump.hidden = !st.showJump;
    };

    scroller.addEventListener("scroll", () => {
      if (programmatic) return;
      apply(nextTailState({
        following: state.following, scrollTop: scroller.scrollTop,
        scrollHeight: scroller.scrollHeight, clientHeight: scroller.clientHeight,
        event: "user-scroll",
      }));
    }, { passive: true });

    jump.addEventListener("click", () => {
      apply(nextTailState({
        following: state.following, scrollTop: scroller.scrollTop,
        scrollHeight: scroller.scrollHeight, clientHeight: scroller.clientHeight,
        event: "jump",
      }));
      toBottom();
    });

    const onContent = () => {
      if (!jump.isConnected) viewer.appendChild(jump);
      const st = nextTailState({
        following: state.following, scrollTop: scroller.scrollTop,
        scrollHeight: scroller.scrollHeight, clientHeight: scroller.clientHeight,
        event: "mutation",
      });
      jump.hidden = !st.showJump;
      if (state.following) toBottom();
      schedule();                             // content changed -> re-measure
    };
    new MutationObserver(onContent).observe(viewer, {
      childList: true, subtree: true, characterData: true,
    });
    toBottom();
  };

  const start = () => {
    releaseStale();
    if (!document.querySelector(VIEWERS)) { requestAnimationFrame(start); return; }
    schedule();

    window.addEventListener("resize", schedule, { passive: true });
    window.addEventListener("scroll", schedule, { passive: true, capture: true });
    if (window.visualViewport) {
      window.visualViewport.addEventListener("resize", schedule, { passive: true });
      window.visualViewport.addEventListener("scroll", schedule, { passive: true });
    }

    const ro = new ResizeObserver(schedule);
    document.querySelectorAll(VIEWERS).forEach((el) => ro.observe(el));
    [LEFT, ".cryostack-right-workspace", ".cryostack-workspace-tabs",
     ".cryostack-output-workspace"].forEach((sel) => {
      const el = document.querySelector(sel);
      if (el) ro.observe(el);
    });
    // the left column's height changes when an accordion expands/collapses or
    // the interaction mode switches -- observe its subtree for that.
    const leftEl = document.querySelector(LEFT);
    if (leftEl) new MutationObserver(schedule).observe(leftEl, {
      childList: true, subtree: true, attributes: true,
      attributeFilter: ["style", "class"],
    });

    document.querySelectorAll(LOG_VIEWER).forEach(wireTail);
    // a tab switch mounts the Run Log viewer late
    const tabs = document.querySelector(".cryostack-workspace-tabs");
    if (tabs) new MutationObserver(() => {
      document.querySelectorAll(LOG_VIEWER).forEach(wireTail);
      schedule();
    }).observe(tabs, { childList: true, subtree: true });

    requestAnimationFrame(schedule);
    setTimeout(schedule, 400);
    setTimeout(schedule, 1200);
  };
  start();
}

if (typeof window !== "undefined" && typeof document !== "undefined") {
  installWorkspaceViewer();
}
