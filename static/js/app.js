(function () {
  'use strict';

  const sheet = document.getElementById('sheet');
  const sheetOverlay = document.getElementById('sheet-overlay');
  const sheetTitle = document.getElementById('sheet-title');
  const sheetBody = document.getElementById('sheet-body');
  const toast = document.getElementById('toast');

  /* ------------------------------------------------------------------ *
   * Theme (light / dark)
   * ------------------------------------------------------------------ */

  const THEME_KEY = 'imparoma-theme';
  const THEME_LIGHT = '#f8fafc';
  const THEME_DARK = '#0f172a';

  function storedTheme() {
    try {
      return localStorage.getItem(THEME_KEY);
    } catch (err) {
      return null;
    }
  }

  function systemTheme() {
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }

  function applyTheme(theme) {
    const dark = theme === 'dark';
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', dark ? THEME_DARK : THEME_LIGHT);
    const toggle = document.querySelector('[data-theme-toggle]');
    if (toggle) toggle.checked = dark;
  }

  function initTheme() {
    const stored = storedTheme();
    applyTheme(stored === 'dark' || stored === 'light' ? stored : systemTheme());
  }

  document.addEventListener('change', (event) => {
    if (!event.target.matches('[data-theme-toggle]')) return;
    const next = event.target.checked ? 'dark' : 'light';
    applyTheme(next);
    try {
      localStorage.setItem(THEME_KEY, next);
    } catch (err) { /* ignore */ }
  });

  /* ------------------------------------------------------------------ *
   * Bottom sheet
   * ------------------------------------------------------------------ */

  function showSheet(title, bodyHtml) {
    if (!sheet) return;
    sheetTitle.textContent = title;
    sheetBody.innerHTML = bodyHtml;
    sheetOverlay.hidden = false;
    sheet.hidden = false;
    requestAnimationFrame(() => {
      sheetOverlay.classList.add('open');
      sheet.classList.add('open');
    });
    document.body.classList.add('sheet-locked');
    if (window.htmx) window.htmx.process(sheetBody);
    sheet.querySelector('[data-sheet-close]')?.focus?.();
  }

  function closeSheet() {
    if (!sheet) return;
    sheetOverlay.classList.remove('open');
    sheet.classList.remove('open');
    document.body.classList.remove('sheet-locked');
    window.setTimeout(() => {
      sheet.hidden = true;
      sheetOverlay.hidden = true;
    }, 200);
  }

  document.addEventListener('click', (event) => {
    if (event.target.closest('[data-sheet-close]')) {
      closeSheet();
      return;
    }
    if (event.target === sheetOverlay) {
      closeSheet();
      return;
    }
    const keywordsBtn = event.target.closest('[data-open-keywords]');
    if (keywordsBtn) {
      const templateId = keywordsBtn.getAttribute('data-open-keywords');
      const tpl = document.getElementById(templateId);
      if (tpl) {
        showSheet('💡 Parole Chiave', tpl.innerHTML);
      }
      return;
    }
    const blankBtn = event.target.closest('.blank-slot');
    if (blankBtn) {
      openBlankSheet(blankBtn);
    }
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeSheet();
  });

  /* Password visibility toggle ------------------------------------------- */
  document.addEventListener('click', (event) => {
    const toggle = event.target.closest('.password-toggle');
    if (!toggle) return;
    const wrap = toggle.closest('.password-wrap');
    const input = wrap && wrap.querySelector('input');
    if (!input) return;
    const visible = input.type === 'text';
    input.type = visible ? 'password' : 'text';
    wrap.classList.toggle('visible', !visible);
    toggle.setAttribute('aria-label', visible ? 'Mostra password' : 'Nascondi password');
  });

  /* ------------------------------------------------------------------ *
   * Part 3 / cloze blank slots
   * ------------------------------------------------------------------ */

  function findBlankSelect(blankButton) {
    const exerciseId = blankButton.dataset.exerciseId;
    const number = blankButton.dataset.blankNumber;
    const zone = blankButton.closest('.answer-zone');
    const selector = '[data-blank-select="' + number + '"]';
    const select = zone ? zone.querySelector(selector) : null;
    if (select) return select;
    // Simulation partials use a different container; fall back to page-wide lookup.
    const pageSelect = document.querySelector('[data-blank-select="' + number + '"]');
    return pageSelect;
  }

  function openBlankSheet(blankButton) {
    const select = findBlankSelect(blankButton);
    if (!select) return;
    const number = blankButton.dataset.blankNumber;
    const options = Array.from(select.options).filter((opt) => opt.value);
    const current = select.value;
    let html = '<div class="sheet-options" role="listbox">';
    options.forEach((opt) => {
      const active = opt.value === current ? ' active' : '';
      html +=
        '<button type="button" class="sheet-option' + active + '" data-value="' +
        opt.value + '">' +
        '<span class="option-key">' + opt.value + '</span>' +
        '<span class="option-text">' + opt.text + '</span>' +
        '</button>';
    });
    html += '</div>';
    showSheet('Lacuna ' + number + ' — scegli la frase', html);

    sheetBody.querySelectorAll('.sheet-option').forEach((btn) => {
      btn.addEventListener('click', () => {
        const value = btn.dataset.value;
        select.value = value;
        updateBlankSlot(blankButton, value, select);
        closeSheet();
      });
    });
  }

  function updateBlankSlot(blankButton, value, select) {
    if (!blankButton) return;
    const valEl = blankButton.querySelector('[data-blank-val]');
    const chosen = select.selectedOptions[0];
    const label = chosen ? chosen.text : '';
    if (valEl) {
      const short = label.length > 60 ? label.slice(0, 60) + '…' : label;
      valEl.textContent = value + ' · ' + short;
    }
    blankButton.classList.add('filled');
  }

  /* ------------------------------------------------------------------ *
   * Simulation: radio styling, timer, grading
   * ------------------------------------------------------------------ */

  document.addEventListener('change', (event) => {
    const radio = event.target;
    if (!radio.matches('.option-list input[type="radio"]')) return;
    const list = radio.closest('.option-list');
    list.querySelectorAll('label.option').forEach((label) => {
      label.classList.toggle('selected', label === radio.closest('label.option'));
    });
  });

  const timerEl = document.getElementById('sim-timer');
  const simSubmitBtn = document.getElementById('sim-submit');
  const simForm = document.getElementById('sim-form');

  let simSubmitted = false;
  let simSecondsLeft = 0;
  let simTimerId = null;

  if (timerEl) {
    const minutes = parseInt(timerEl.dataset.minutes, 10) || 40;
    simSecondsLeft = minutes * 60;
    renderTimer();
    simTimerId = window.setInterval(() => {
      simSecondsLeft -= 1;
      if (simSecondsLeft <= 0) {
        simSecondsLeft = 0;
        renderTimer();
        window.clearInterval(simTimerId);
        if (!simSubmitted) submitSimulation(true);
        return;
      }
      renderTimer();
    }, 1000);
  }

  function renderTimer() {
    const m = Math.floor(simSecondsLeft / 60);
    const s = simSecondsLeft % 60;
    timerEl.textContent = String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0');
    if (simSecondsLeft <= 300) timerEl.classList.add('warning');
  }

  if (simSubmitBtn) {
    simSubmitBtn.addEventListener('click', () => submitSimulation(false));
  }

  function collectSession() {
    const zones = document.querySelectorAll('#sim-form .answer-zone');
    const session = [];
    zones.forEach((zone) => {
      const exerciseId = zone.dataset.exerciseId;
      const part = zone.dataset.part;
      const answers = {};
      if (part === '1') {
        const checked = zone.querySelector('input[type="radio"]:checked');
        answers.answer = checked ? checked.value : '';
      } else {
        zone.querySelectorAll('select').forEach((sel) => {
          if (sel.value) answers[sel.name] = sel.value;
        });
      }
      session.push({ exercise_id: exerciseId, answers: answers });
    });
    return session;
  }

  function submitSimulation(expired) {
    if (simSubmitted) return;
    simSubmitted = true;
    if (simTimerId) window.clearInterval(simTimerId);
    if (simSubmitBtn) {
      simSubmitBtn.disabled = true;
      simSubmitBtn.textContent = 'Verifica in corso…';
    }
    const session = collectSession();
    const mode = simForm ? simForm.dataset.mode || 'real' : 'real';
    fetch('/simulation/grade', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: mode, session: session }),
    })
      .then((resp) => resp.text())
      .then((html) => {
        if (simForm) simForm.style.display = 'none';
        const target = document.getElementById('sim-result');
        if (target) target.innerHTML = html;
        if (expired) showToast('⏱️ Tempo scaduto: esercizio consegnato.');
      })
      .catch(() => {
        simSubmitted = false;
        if (simSubmitBtn) {
          simSubmitBtn.disabled = false;
          simSubmitBtn.textContent = 'Consegna e verifica';
        }
        showToast('Errore durante la consegna. Riprova.');
      });
  }

  /* ------------------------------------------------------------------ *
   * Vocabulary delete confirmation
   * ------------------------------------------------------------------ */

  document.addEventListener('submit', (event) => {
    const form = event.target.closest('form.confirm-delete');
    if (form) {
      let term = '';
      try {
        term = JSON.parse(form.dataset.term || '""');
      } catch (err) {
        term = '';
      }
      const message = form.dataset.confirmMsg
        ? form.dataset.confirmMsg
        : 'Eliminare «' + term + '» dal vocabolario?';
      if (!window.confirm(message)) {
        event.preventDefault();
      }
    }
    const resetForm = event.target.closest('form[data-confirm-reset]');
    if (resetForm) {
      if (!window.confirm('Ricominciare da zero il percorso? Tutti i progressi verranno cancellati.')) {
        event.preventDefault();
      }
    }
  });

  /* ------------------------------------------------------------------ *
   * Toast
   * ------------------------------------------------------------------ */

  let toastTimer = null;
  function showToast(message) {
    if (!toast) return;
    toast.textContent = message;
    toast.hidden = false;
    toast.classList.add('open');
    if (toastTimer) window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => {
      toast.classList.remove('open');
      toast.hidden = true;
    }, 3000);
  }

  /* ------------------------------------------------------------------ *
   * PWA
   * ------------------------------------------------------------------ */

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/static/js/sw.js').catch(() => {});
    });
  }
})();
