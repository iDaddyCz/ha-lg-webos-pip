/*
 * App settings, layered (later wins):
 *   built-in defaults < config.js (optional, baked from .env at build time)
 *   < settings saved on the TV (setup screen, or pushed by the HA integration)
 * Launch params from Home Assistant then override per launch (see app.js).
 */
(function (global) {
  'use strict';

  var KEY = 'lgwebospip.settings';
  var DEFAULTS = {
    url: '',
    token: '',
    camera: '',
    mode: 'mjpeg',
    position: 'top-right',
    size: 30,
    timeout: 30
  };

  function readSaved() {
    try {
      return JSON.parse(global.localStorage.getItem(KEY)) || {};
    } catch (e) {
      return {};
    }
  }

  var Store = {
    DEFAULTS: DEFAULTS,

    /** Effective settings: defaults, then config.js, then saved values. */
    get: function () {
      var out = {};
      [DEFAULTS, global.HA_CONFIG || {}, readSaved()].forEach(function (layer) {
        Object.keys(layer).forEach(function (k) {
          if (layer[k] !== undefined && layer[k] !== null && layer[k] !== '') out[k] = layer[k];
        });
      });
      if (out.url) out.url = String(out.url).replace(/\/+$/, '');
      return out;
    },

    /** Merges `values` into the saved settings. */
    save: function (values) {
      var saved = readSaved();
      Object.keys(values).forEach(function (k) { saved[k] = values[k]; });
      try {
        global.localStorage.setItem(KEY, JSON.stringify(saved));
        return true;
      } catch (e) {
        return false;
      }
    },

    isConnectionSet: function () {
      var s = this.get();
      return !!(s.url && s.token);
    }
  };

  global.Store = Store;
})(window);
