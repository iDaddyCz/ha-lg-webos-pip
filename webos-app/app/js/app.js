/*
 * HA PIP: shows one Home Assistant camera (or any video URL) in a small box
 * over whatever the TV is playing, then closes itself.
 *
 * Launch params (sent by the Home Assistant integration via
 * webostv.command -> system.launcher/launch):
 *   {camera | url, title, mode, position, size, timeout, muted, refresh}
 *       show a PIP; launching again while open swaps the feed
 *   {close: true}                     hide the PIP
 *   {connect: {url, token}}           store the HA connection on the TV
 *                                     (may be combined with a camera)
 *   {} / {settings: true}             open the setup screen (app list launch)
 */
(function () {
  'use strict';

  var KEY_BACK = 461, KEY_ENTER = 13, KEY_ESC = 27;
  var POSITIONS = ['top-right', 'top-left', 'bottom-right', 'bottom-left'];
  var RETRY_DELAY = 3000;

  var webos = window.webOSSystem || window.PalmSystem || null;
  var appInfo = window.APP_INFO || {};

  var pip = document.getElementById('pip');
  var label = document.getElementById('label');
  var errorBox = document.getElementById('error');
  var spinner = document.getElementById('spinner');
  var video = document.getElementById('video');
  var toast = document.getElementById('toast');

  var ha = null;
  var haKey = '';          // url|token the current client was made for
  var closeTimer = null;
  var retryTimer = null;
  var toastTimer = null;
  var showId = 0;          // bumped per show()/closePip() so stale retries stop
  var returnToSettings = false;

  var player = new Player(video, document.getElementById('frame'), function (state, info) {
    spinner.classList.toggle('hidden', state !== 'loading');
    // Size the box to the feed (e.g. 4:3 doorbells) without CSS aspect-ratio,
    // which is unavailable in the Chromium 87 engine used by webOS 22.
    if (state === 'playing' && info.width && info.height && !pip.classList.contains('fill')) {
      pip.style.height = Math.round(pip.getBoundingClientRect().width * info.height / info.width) + 'px';
    }
  });

  // ---------- launch params ----------

  function parseParams(raw) {
    if (!raw) return {};
    if (typeof raw === 'object') return raw;
    try { return JSON.parse(raw); } catch (e) { return {}; }
  }

  function initialParams() {
    if (webos) return parseParams(webos.launchParams);
    // Desktop browser testing: index.html?camera=camera.front_door&mode=hls
    var out = {};
    location.search.replace(/^\?/, '').split('&').forEach(function (kv) {
      if (!kv) return;
      var i = kv.indexOf('=');
      out[decodeURIComponent(i < 0 ? kv : kv.slice(0, i))] = i < 0 ? '' : decodeURIComponent(kv.slice(i + 1));
    });
    return out;
  }

  /** Launch params override the saved settings. */
  function resolve(params, settings) {
    function pick(key) {
      return params[key] !== undefined && params[key] !== '' ? params[key] : settings[key];
    }
    var url = params.url || '';
    var position = pick('position');
    return {
      camera: url ? '' : (pick('camera') || ''),
      url: url,
      title: params.title || '',
      mode: pick('mode') || 'mjpeg',
      position: POSITIONS.indexOf(position) >= 0 ? position : 'top-right',
      size: clamp(Number(pick('size')), 10, 100) / 100,
      timeout: Math.max(0, Number(pick('timeout')) || 0),
      refresh: Number(params.refresh) || 500,
      muted: String(params.muted === undefined ? true : params.muted) !== 'false'
    };
  }

  function route(params) {
    if (params.connect && params.connect.url && params.connect.token) {
      Store.save({ url: String(params.connect.url).replace(/\/+$/, ''), token: params.connect.token });
    }
    if (params.close) {
      closePip();
    } else if (params.camera || params.url) {
      Settings.close();
      returnToSettings = false;
      show(params, Store.get());
    } else if (params.connect) {
      if (Settings.isOpen()) {
        openSettings(); // reload the form with the pushed connection
        showToast('Connection received from Home Assistant');
      } else {
        notice('Connected to Home Assistant ✓', 6);
      }
    } else {
      openSettings();
    }
  }

  // ---------- Home Assistant connection ----------

  function connectHA(conn) {
    var key = conn.url + '|' + conn.token;
    if (ha && ha.connected && haKey === key) return Promise.resolve(ha);
    if (!conn.url || !conn.token) {
      var err = new Error('Not set up yet: open HA PIP from the TV\'s app list, or add the access token in the Home Assistant integration.');
      err.fatal = true;
      return Promise.reject(err);
    }
    if (ha) ha.close();
    ha = new HAClient(conn.url, conn.token);
    haKey = key;
    return ha.connect().then(function () { return ha; });
  }

  // ---------- PIP ----------

  function preparePip(opts) {
    clearTimeout(closeTimer);
    clearTimeout(retryTimer);
    hideError();
    pip.classList.remove('hidden', 'closing');
    POSITIONS.forEach(function (p) { pip.classList.toggle(p, p === opts.position); });
    // If webOS sized the overlay window itself, fill it. Otherwise give the box
    // explicit dimensions so older webOS engines cannot collapse it to a bar.
    var fill = !!webos && window.innerWidth < 1200;
    pip.classList.toggle('fill', fill);
    pip.style.width = fill ? '' : Math.round(window.innerWidth * opts.size) + 'px';
    pip.style.height = fill ? '' : Math.round(window.innerWidth * opts.size * 9 / 16) + 'px';
    if (opts.timeout > 0) closeTimer = setTimeout(closePip, opts.timeout * 1000);
  }

  function show(params, settings) {
    var opts = resolve(params, settings);
    var id = ++showId;
    player.stop();
    preparePip(opts);
    video.muted = opts.muted;
    label.textContent = opts.title;

    if (!opts.camera && !opts.url) {
      showError('No camera chosen. Pick a default camera in setup, or choose one in Home Assistant.');
      return;
    }
    attempt(id, opts, { url: settings.url, token: settings.token });
  }

  /** HA or the camera can take a while to respond, so keep retrying while the PIP is open. */
  function attempt(id, opts, conn) {
    connectHA(conn).then(function (client) {
      if (id !== showId) return;
      if (!label.textContent && opts.camera) {
        client.friendlyName(opts.camera).then(function (n) {
          if (id === showId && !label.textContent) label.textContent = n;
        }, function () {});
      }
      return player.play(client, opts).then(hideError);
    }).catch(function (err) {
      if (id !== showId) return;
      showError((err.message || String(err)) + (err.fatal ? '' : ' (retrying…)'));
      if (!err.fatal) retryTimer = setTimeout(function () { attempt(id, opts, conn); }, RETRY_DELAY);
    });
  }

  /** A text-only PIP, e.g. after Home Assistant pushed the connection settings. */
  function notice(text, seconds) {
    showId++;
    player.stop();
    var s = Store.get();
    preparePip(resolve({ timeout: seconds }, s));
    label.textContent = '';
    spinner.classList.add('hidden');
    errorBox.textContent = text;
    errorBox.classList.add('info');
    errorBox.classList.remove('hidden');
  }

  function closePip() {
    showId++;
    clearTimeout(closeTimer);
    clearTimeout(retryTimer);
    pip.classList.add('closing');
    setTimeout(function () {
      player.stop();
      pip.classList.add('hidden');
      if (returnToSettings) {
        returnToSettings = false;
        Settings.resume();
      } else {
        exitApp();
      }
    }, 300);
  }

  function showError(msg) {
    spinner.classList.add('hidden');
    errorBox.classList.remove('info');
    errorBox.textContent = msg;
    errorBox.classList.remove('hidden');
  }

  function hideError() {
    errorBox.classList.add('hidden');
  }

  // ---------- setup screen ----------

  function openSettings() {
    showId++;
    clearTimeout(closeTimer);
    clearTimeout(retryTimer);
    player.stop();
    pip.classList.add('hidden');
    Settings.open({
      version: (appInfo.title || 'HA PIP') + ' ' + (appInfo.version || ''),
      toast: showToast,
      onExit: exitApp,
      onPreview: function (draft) {
        Settings.hide();
        returnToSettings = true;
        // Preview uses the unsaved draft, connection included.
        show({ camera: draft.camera, timeout: draft.timeout || 15, title: 'Preview: OK or Back to return' }, draft);
      }
    });
  }

  function showToast(text) {
    clearTimeout(toastTimer);
    toast.textContent = text;
    toast.classList.remove('hidden');
    toastTimer = setTimeout(function () { toast.classList.add('hidden'); }, 2500);
  }

  function exitApp() {
    Settings.close();
    if (ha) ha.close();
    ha = null;
    if (webos && typeof webos.close === 'function') webos.close();
    else window.close();
  }

  function clamp(n, lo, hi) {
    return isNaN(n) ? 30 : Math.min(hi, Math.max(lo, n));
  }

  // ---------- events ----------

  document.addEventListener('webOSRelaunch', function (e) {
    route(parseParams(e.detail || (webos && webos.launchParams)));
  });

  // The overlay window takes the remote while it's open: in setup the keys
  // drive the form; over a PIP, Back or OK dismisses it.
  document.addEventListener('keydown', function (e) {
    if (Settings.isOpen()) {
      if (Settings.handleKey(e)) e.preventDefault();
    } else if (e.keyCode === KEY_BACK || e.keyCode === KEY_ESC || e.keyCode === KEY_ENTER) {
      e.preventDefault();
      closePip();
    }
  });

  document.addEventListener('visibilitychange', function () {
    if (document.hidden) player.stop();
  });

  route(initialParams());
})();
