/*
 * On-TV setup screen, driven by the remote (arrows / OK / Back) or the
 * Magic Remote pointer. Edits a draft; "Save" writes it to Store.
 */
(function (global) {
  'use strict';

  var KEY = { LEFT: 37, UP: 38, RIGHT: 39, DOWN: 40, ENTER: 13, BACK: 461, ESC: 27 };

  var CHOICES = {
    mode: [
      ['mjpeg', 'MJPEG (recommended over live TV)'],
      ['snapshot', 'Snapshots (works with every camera)'],
      ['hls', 'HLS video'],
      ['webrtc', 'WebRTC (lowest latency)']
    ],
    position: [
      ['top-right', 'Top right'],
      ['top-left', 'Top left'],
      ['bottom-right', 'Bottom right'],
      ['bottom-left', 'Bottom left']
    ],
    size: [10, 15, 20, 25, 30, 35, 40, 50, 60].map(function (n) { return [n, n + ' % of screen width']; }),
    timeout: [0, 10, 15, 20, 30, 45, 60, 90, 120, 180, 300].map(function (n) {
      return [n, n === 0 ? 'Never (close with Back)' : n + ' seconds'];
    }),
    camera: [['', 'None (Home Assistant always chooses)']]
  };

  var root = document.getElementById('settings');
  var statusEl = document.getElementById('s-status');
  var rows = [].slice.call(root.querySelectorAll('.row'));
  var draft = {};
  var focus = { row: 0, col: 0 };
  var callbacks = {};
  var client = null;

  function rowItems(row) {
    return [].slice.call(row.querySelectorAll('input, button, .value')).filter(function (el) {
      return !(row.classList.contains('choice') && el.tagName === 'INPUT');
    });
  }

  function focusedEl() {
    var items = rowItems(rows[focus.row]);
    return items[Math.min(focus.col, items.length - 1)];
  }

  function render() {
    rows.forEach(function (row) {
      var key = row.getAttribute('data-key');
      if (row.classList.contains('choice')) {
        var opts = CHOICES[key];
        var current = opts.filter(function (o) { return String(o[0]) === String(draft[key]); })[0];
        // A saved camera that isn't in the (not yet loaded) list still shows its id.
        row.querySelector('.value').textContent = current ? current[1] : String(draft[key] || '');
      } else if (key) {
        var input = row.querySelector('input');
        if (document.activeElement !== input) input.value = draft[key] || '';
      }
    });
    root.querySelectorAll('.focused').forEach(function (el) { el.classList.remove('focused'); });
    rows[focus.row].classList.add('focused');
    var el = focusedEl();
    if (el) {
      el.classList.add('focused');
      el.scrollIntoView({ block: 'nearest' });
    }
  }

  function setStatus(text, kind) {
    statusEl.textContent = text;
    statusEl.className = 'status' + (kind ? ' ' + kind : '');
  }

  function cycle(key, step) {
    var opts = CHOICES[key];
    var idx = -1;
    opts.forEach(function (o, i) { if (String(o[0]) === String(draft[key])) idx = i; });
    idx = (idx + step + opts.length) % opts.length;
    draft[key] = opts[idx][0];
    render();
  }

  function readInputs() {
    rows.forEach(function (row) {
      var key = row.getAttribute('data-key');
      var input = row.querySelector('input');
      if (key && input) draft[key] = input.value.trim();
    });
    draft.url = (draft.url || '').replace(/\/+$/, '');
  }

  function testConnection() {
    readInputs();
    if (!draft.url || !draft.token) {
      setStatus('Enter the URL and token first', 'bad');
      return Promise.resolve(false);
    }
    setStatus('Connecting…');
    if (client) client.close();
    client = new HAClient(draft.url, draft.token);
    return client.connect()
      .then(function () { return Promise.all([client.currentUser(), client.listCameras()]); })
      .then(function (res) {
        CHOICES.camera = [CHOICES.camera[0]].concat(res[1].map(function (c) { return [c.id, c.name]; }));
        setStatus('Connected to Home Assistant ' + client.haVersion + ' as ' + res[0].name +
          ' · ' + res[1].length + ' cameras', 'ok');
        render();
        return true;
      })
      .catch(function (err) {
        setStatus(err.message || String(err), 'bad');
        return false;
      });
  }

  function save() {
    readInputs();
    var ok = Store.save({
      url: draft.url, token: draft.token, camera: draft.camera, mode: draft.mode,
      position: draft.position, size: Number(draft.size), timeout: Number(draft.timeout)
    });
    if (callbacks.toast) callbacks.toast(ok ? 'Settings saved' : 'Could not save settings');
  }

  function act(action) {
    if (action === 'test') testConnection();
    else if (action === 'save') save();
    else if (action === 'preview') {
      readInputs();
      if (callbacks.onPreview) callbacks.onPreview(Object.assign({}, draft));
    } else if (action === 'exit' && callbacks.onExit) callbacks.onExit();
  }

  function activate(el) {
    if (!el) return;
    if (el.tagName === 'INPUT') {
      el.focus(); // webOS opens its on-screen keyboard
    } else if (el.tagName === 'BUTTON') {
      act(el.getAttribute('data-action'));
    } else if (el.classList.contains('value')) {
      cycle(el.parentNode.getAttribute('data-key'), 1);
    }
  }

  function move(dRow, dCol) {
    if (dRow) {
      focus.row = Math.max(0, Math.min(rows.length - 1, focus.row + dRow));
      focus.col = 0;
    } else {
      var n = rowItems(rows[focus.row]).length;
      focus.col = Math.max(0, Math.min(n - 1, focus.col + dCol));
    }
    render();
  }

  /** Returns true if the key was handled. */
  function handleKey(e) {
    var el = focusedEl();
    var row = rows[focus.row];

    // While typing in an input, only Up/Down/OK/Back leave it; the rest edit text.
    if (document.activeElement && document.activeElement.tagName === 'INPUT') {
      if (e.keyCode === KEY.UP || e.keyCode === KEY.DOWN || e.keyCode === KEY.ENTER ||
          e.keyCode === KEY.BACK || e.keyCode === KEY.ESC) {
        document.activeElement.blur();
        readInputs();
        if (e.keyCode === KEY.UP) move(-1, 0);
        else if (e.keyCode === KEY.DOWN) move(1, 0);
        else render();
        return true;
      }
      return false;
    }

    switch (e.keyCode) {
      case KEY.UP: move(-1, 0); return true;
      case KEY.DOWN: move(1, 0); return true;
      case KEY.LEFT:
      case KEY.RIGHT:
        var dir = e.keyCode === KEY.LEFT ? -1 : 1;
        if (row.classList.contains('choice')) cycle(row.getAttribute('data-key'), dir);
        else move(0, dir);
        return true;
      case KEY.ENTER: activate(el); return true;
      case KEY.BACK:
      case KEY.ESC:
        if (callbacks.onExit) callbacks.onExit();
        return true;
    }
    return false;
  }

  // Magic Remote pointer / mouse
  root.addEventListener('click', function (e) {
    var target = e.target.closest('input, button, .value');
    var row = e.target.closest('.row');
    if (!row) return;
    focus.row = rows.indexOf(row);
    focus.col = Math.max(0, rowItems(row).indexOf(target));
    render();
    if (target && target.tagName !== 'INPUT') activate(target);
  });
  root.addEventListener('change', readInputs, true);

  var Settings = {
    open: function (opts) {
      callbacks = opts || {};
      var s = Store.get();
      draft = {
        url: s.url || '', token: s.token || '', camera: s.camera || '', mode: s.mode,
        position: s.position, size: Number(s.size), timeout: Number(s.timeout)
      };
      root.classList.remove('hidden');
      document.body.classList.add('settings-open');
      focus = { row: draft.url && draft.token ? rows.indexOf(root.querySelector('[data-key="camera"]')) : 0, col: 0 };
      document.getElementById('s-version').textContent = callbacks.version || '';
      render();
      if (draft.url && draft.token) testConnection();
      else setStatus('Not connected yet', '');
    },
    /** Hide without forgetting the draft (used by Preview). */
    hide: function () {
      root.classList.add('hidden');
      document.body.classList.remove('settings-open');
    },
    resume: function () {
      root.classList.remove('hidden');
      document.body.classList.add('settings-open');
      render();
    },
    close: function () {
      this.hide();
      if (client) client.close();
      client = null;
    },
    isOpen: function () { return !root.classList.contains('hidden'); },
    handleKey: handleKey
  };

  global.Settings = Settings;
})(window);
