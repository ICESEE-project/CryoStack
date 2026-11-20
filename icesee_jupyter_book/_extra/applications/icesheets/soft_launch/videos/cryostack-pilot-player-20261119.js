/* Scoped progressive enhancement for public CryoStack tutorial videos. */
(() => {
  'use strict';
  const selector = '[data-cryostack-pilot-player]';
  const previous = window.CryoStackPilotPlayer;
  if (previous && previous.version === '20261119') {
    previous.init(document);
    return;
  }
  const initialized = new WeakSet();
  let instanceCount = 0;
  let activeCinema = null;

  function namespace(root) {
    const allIds = new Set([...document.querySelectorAll('[id]')].map(item => item.id));
    let prefix;
    do { prefix = 'cryostack-pilot-' + (++instanceCount); }
    while ([...allIds].some(id => id.startsWith(prefix + '-')));
    const elements = [root, ...root.querySelectorAll('[id]')];
    const names = new Map();
    elements.forEach((element, index) => {
      const id = prefix + '-' + index;
      if (element.id) names.set(element.id, id);
      element.id = id;
    });
    [root, ...root.querySelectorAll('*')].forEach(element => {
      ['for', 'aria-labelledby', 'aria-describedby', 'aria-controls'].forEach(attribute => {
        if (element.hasAttribute(attribute)) element.setAttribute(attribute,
          element.getAttribute(attribute).split(/\s+/).map(id => names.get(id) || id).join(' '));
      });
      const href = element.getAttribute('href');
      if (href && href.startsWith('#') && names.has(href.slice(1))) element.setAttribute('href', '#' + names.get(href.slice(1)));
    });
  }

  function init(scope = document) {
    const roots = [...scope.querySelectorAll(selector)];
    if (scope.matches && scope.matches(selector)) roots.unshift(scope);
    roots.forEach(enhance);
  }

  function enhance(root) {
    if (initialized.has(root)) return;
    const video = root.querySelector('video');
    const source = root.querySelector('[data-pilot-metadata]');
    const chapters = [...root.querySelectorAll('[data-pilot-chapter]')];
    const cards = [...root.querySelectorAll('[data-pilot-step]')];
    const status = root.querySelector('[data-pilot-status]');
    let metadata;
    try { metadata = JSON.parse(source.textContent); } catch (_) { return; }
    if (!video || !metadata || typeof metadata !== 'object' || !Array.isArray(metadata.steps) || !metadata.steps.length) return;
    const steps = metadata.steps;
    if (steps.length !== chapters.length || steps.length !== cards.length) return;
    if (!steps.every((step, i) => step && typeof step === 'object' && Number.isFinite(step.start) && Number.isFinite(step.end)
      && step.start >= 0 && step.end > step.start && (i === 0 || step.start >= steps[i - 1].end - 0.01)
      && chapters[i].hash === '#' + cards[i].id)) return;

    namespace(root);
    initialized.add(root);
    root.dataset.pilotInitialized = 'true';
    root.dataset.pilotEnhanced = 'true';
    const cinema = root.querySelector('[data-pilot-cinema]');
    const pause = root.querySelector('[data-pilot-try]');
    const prev = root.querySelector('[data-pilot-prev]');
    const next = root.querySelector('[data-pilot-next]');
    const count = root.querySelector('[data-pilot-count]');
    const checks = [...root.querySelectorAll('[data-pilot-check]')];
    const progress = root.querySelector('[data-pilot-progress]');
    const panel = root.querySelector('[data-pilot-instructions]');
    const guidedButton = root.querySelector('[data-pilot-guided-start]');
    const guidedToggle = root.querySelector('[data-pilot-guided-toggle]');
    const continueButton = root.querySelector('[data-pilot-continue]');
    const guidedHelp = root.querySelector('[data-pilot-guided-help]');
    let active = -1;
    let pendingSeek = null;
    let outside = [];
    let guidedMode = false;
    let guidedIndex = 0;
    let waiting = false;
    let internalSeekTarget = null;
    let animation = null;
    const announce = text => { if (status) status.textContent = text; };

    function currentIndex() {
      const time = video.currentTime || 0;
      let index = 0;
      for (let i = 1; i < steps.length; i++) {
        if (time + 0.03 >= steps[i].start) index = i; else break;
      }
      return index;
    }

    function show(index) {
      if (index === active) return;
      const moveFocus = active >= 0 && cards[active].contains(document.activeElement);
      active = index;
      chapters.forEach((chapter, i) => {
        if (i === index) chapter.setAttribute('aria-current', 'step');
        else chapter.removeAttribute('aria-current');
      });
      cards.forEach((card, i) => { card.hidden = i !== index; });
      if (moveFocus) {
        const heading = cards[index].querySelector('h3');
        if (heading) heading.focus({preventScroll: true});
      }
      if (count) count.textContent = 'Step ' + (index + 1) + ' of ' + steps.length;
      if (prev) prev.disabled = index === 0;
      if (next) next.disabled = index === steps.length - 1;
    }

    function applySeek(index) {
      const time = steps[index].start;
      try {
        const target = Number.isFinite(video.duration) ? Math.min(time, Math.max(0, video.duration - 0.05)) : time;
        internalSeekTarget = target;
        video.currentTime = target;
        if (Math.abs(video.currentTime - target) > 0.25) throw new Error('Seek was not applied');
        show(currentIndex());
        announce('Moved to ' + chapters[index].textContent.trim() + '. Press Play to watch.');
        return true;
      } catch (_) {
        internalSeekTarget = null;
        guidedIndex = currentIndex();
        show(currentIndex());
        announce('That chapter could not be opened. Use the video controls or the written steps.');
        return false;
      }
    }
    function seek(index) {
      guidedIndex = index;
      waiting = false;
      if (video.readyState < 1) {
        pendingSeek = index;
        announce('Video timing is loading. Your selected chapter will open when it is ready.');
      } else applySeek(index);
      updateGuidedControls();
    }

    function updateGuidedControls() {
      root.dataset.pilotGuided = !guidedMode ? 'off' : waiting ? 'waiting' : video.paused ? 'paused' : 'playing';
      if (guidedButton) {
        guidedButton.textContent = guidedMode ? 'Exit guided walkthrough' : 'Start guided walkthrough';
        guidedButton.setAttribute('aria-pressed', String(guidedMode));
        guidedButton.disabled = video.readyState < 1;
      }
      if (guidedToggle) { guidedToggle.checked = guidedMode; guidedToggle.disabled = video.readyState < 1; }
      if (guidedHelp) guidedHelp.hidden = !guidedMode;
      if (continueButton) {
        continueButton.hidden = !guidedMode || (!waiting && !video.paused);
        continueButton.textContent = waiting ? (guidedIndex === steps.length - 1 ? 'Finish walkthrough' : 'Continue to next step') : 'Resume this step';
      }
    }
    function stopWatch() {
      if (animation !== null) cancelAnimationFrame(animation);
      animation = null;
    }
    function setGuided(enabled) {
      stopWatch();
      guidedMode = enabled;
      guidedIndex = currentIndex();
      waiting = false;
      updateGuidedControls();
    }
    function boundary() {
      if (!guidedMode || waiting || video.seeking) return;
      while (video.currentTime >= steps[guidedIndex].end - 0.025) {
        if (steps[guidedIndex].pauseAfter === false && guidedIndex < steps.length - 1) {
          guidedIndex += 1;
          show(guidedIndex);
          continue;
        }
        waiting = true;
        video.pause();
        const hold = Math.max(steps[guidedIndex].start, steps[guidedIndex].end - 0.08);
        try { internalSeekTarget = hold; video.currentTime = hold; } catch (_) { internalSeekTarget = null; }
        show(guidedIndex);
        updateGuidedControls();
        announce('This recorded step has reached its confirmation. Try the action, then choose Continue. Your checklist is yours to mark.');
        break;
      }
    }
    function watch() {
      animation = null;
      if (!guidedMode || waiting || video.paused) return;
      boundary();
      if (guidedMode && !waiting && !video.paused) animation = requestAnimationFrame(watch);
    }
    function syncPlayback() {
      boundary();
      show(guidedMode && waiting ? guidedIndex : currentIndex());
    }
    function playSelected(index, restart) {
      guidedIndex = index;
      waiting = false;
      if (restart && !applySeek(index)) { updateGuidedControls(); return; }
      const result = video.play();
      if (result && result.catch) result.catch(() => {
        updateGuidedControls();
        announce('Press Play to watch this step.');
      });
      updateGuidedControls();
    }
    if (guidedButton) guidedButton.addEventListener('click', () => {
      if (guidedMode) { video.pause(); setGuided(false); announce('Guided mode closed. Use Play for continuous playback.'); }
      else { setGuided(true); playSelected(currentIndex(), true); }
    });
    if (guidedToggle) guidedToggle.addEventListener('change', () => {
      setGuided(guidedToggle.checked);
      if (guidedMode && !video.paused) watch();
      announce(guidedMode ? 'Pause after each recorded step is on.' : 'Continuous playback is on.');
    });
    if (continueButton) continueButton.addEventListener('click', () => {
      if (waiting && guidedIndex === steps.length - 1) {
        setGuided(false);
        announce('Walkthrough finished. Mark your own checklist for actions you have completed.');
      } else playSelected(waiting ? guidedIndex + 1 : guidedIndex, waiting);
    });

    chapters.forEach((chapter, index) => chapter.addEventListener('click', event => {
      event.preventDefault();
      video.pause();
      seek(index);
    }));
    video.addEventListener('loadedmetadata', () => {
      if (pendingSeek !== null) {
        const index = pendingSeek;
        pendingSeek = null;
        applySeek(index);
      }
      show(currentIndex());
      updateGuidedControls();
    });
    video.addEventListener('seeking', () => {
      if (guidedMode && (internalSeekTarget === null || Math.abs(video.currentTime - internalSeekTarget) > 0.01)) {
        guidedIndex = currentIndex();
        waiting = false;
        updateGuidedControls();
      }
    });
    video.addEventListener('seeked', () => { internalSeekTarget = null; syncPlayback(); });
    ['timeupdate', 'ended'].forEach(event => video.addEventListener(event, syncPlayback));
    video.addEventListener('play', () => {
      if (guidedMode && waiting) { video.pause(); announce('Choose Continue when you are ready for the next step.'); return; }
      updateGuidedControls();
      if (guidedMode) { stopWatch(); watch(); }
    });
    video.addEventListener('pause', () => { stopWatch(); updateGuidedControls(); });
    if (prev) prev.addEventListener('click', () => { video.pause(); seek(Math.max(0, active - 1)); });
    if (next) next.addEventListener('click', () => { video.pause(); seek(Math.min(steps.length - 1, active + 1)); });
    if (pause) pause.addEventListener('click', () => {
      video.pause();
      show(currentIndex());
      const heading = cards[active].querySelector('h3');
      if (heading) heading.focus();
      announce('Video paused. Try the current step in CryoLauncher, then return here.');
    });
    const updateProgress = () => {
      if (progress) progress.textContent = checks.filter(item => item.checked).length + ' of ' + checks.length + ' steps checked';
    };
    checks.forEach(check => check.addEventListener('change', updateProgress));
    updateProgress();
    setGuided(false);

    function exitCinema(restoreFocus = true) {
      if (root.dataset.pilotCinema !== 'true') return;
      root.dataset.pilotCinema = 'false';
      root.setAttribute('role', 'region');
      root.removeAttribute('aria-modal');
      cinema.setAttribute('aria-pressed', 'false');
      cinema.setAttribute('aria-expanded', 'false');
      cinema.textContent = 'Cinema view';
      outside.forEach(item => {
        if (item.inert === null) item.element.removeAttribute('inert');
        else item.element.setAttribute('inert', item.inert);
        if (item.ariaHidden === null) item.element.removeAttribute('aria-hidden');
        else item.element.setAttribute('aria-hidden', item.ariaHidden);
      });
      outside = [];
      if (activeCinema && activeCinema.root === root) activeCinema = null;
      if (restoreFocus && cinema.isConnected) cinema.focus();
      announce('Cinema view closed.');
    }
    if (cinema) cinema.addEventListener('click', () => {
      if (root.dataset.pilotCinema === 'true') { exitCinema(); return; }
      if (activeCinema) activeCinema.exit(false);
      let branch = root;
      while (branch.parentElement && branch !== document.body) {
        [...branch.parentElement.children].filter(item => item !== branch).forEach(element => {
          outside.push({element, inert: element.getAttribute('inert'), ariaHidden: element.getAttribute('aria-hidden')});
          element.setAttribute('inert', '');
          if (!('inert' in element)) element.setAttribute('aria-hidden', 'true');
        });
        branch = branch.parentElement;
      }
      root.dataset.pilotCinema = 'true';
      root.setAttribute('role', 'dialog');
      root.setAttribute('aria-modal', 'true');
      cinema.setAttribute('aria-pressed', 'true');
      cinema.setAttribute('aria-expanded', 'true');
      cinema.textContent = 'Exit cinema';
      activeCinema = {root, exit: exitCinema, button: cinema};
      cinema.focus();
      announce('Cinema view opened. Press Escape to close it.');
    });
    root.addEventListener('keydown', event => {
      if (root.dataset.pilotCinema !== 'true') return;
      if (event.key !== 'Tab') return;
      const focusable = [...root.querySelectorAll('a[href],button,input,video,[tabindex]')]
        .filter(item => !item.disabled && item.tabIndex >= 0 && item.getClientRects().length > 0 && !item.closest('[hidden]'));
      if (!focusable.length) return;
      const first = focusable[0], last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    });
    if (cinema) {
      root.dataset.pilotCinema = 'false';
      root.setAttribute('role', 'region');
      root.removeAttribute('aria-modal');
      cinema.setAttribute('aria-controls', root.id);
      cinema.setAttribute('aria-pressed', 'false');
      cinema.setAttribute('aria-expanded', 'false');
      cinema.textContent = 'Cinema view';
    }
    root.querySelectorAll('[data-pilot-enhancement]').forEach(item => { item.hidden = false; });
    show(currentIndex());
    if (panel) panel.setAttribute('aria-label', 'Instructions for the current tutorial step');
  }

  document.addEventListener('keydown', event => {
    if (activeCinema && event.key === 'Escape') { event.preventDefault(); activeCinema.exit(); }
  });
  document.addEventListener('focusin', event => {
    if (activeCinema && !activeCinema.root.contains(event.target)) activeCinema.button.focus();
  });

  window.CryoStackPilotPlayer = Object.freeze({version: '20261119', init});
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => init(), {once: true});
  else init();
})();
