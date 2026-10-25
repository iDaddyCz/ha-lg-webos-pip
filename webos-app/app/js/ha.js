/*
 * Minimal Home Assistant WebSocket API client.
 *
 * Everything goes over the WebSocket (no REST/fetch), which sidesteps CORS:
 * the app runs from file:// on the TV and HA only sends CORS headers for
 * origins listed in http.cors_allowed_origins.
 */
(function (global) {
  'use strict';

  function HAClient(baseUrl, token) {
    this.baseUrl = String(baseUrl || '').replace(/\/+$/, '');
    this.token = token;
    this.ws = null;
    this.nextId = 1;
    this.pending = {};        // id -> {resolve, reject}
    this.subscriptions = {};  // id -> callback
    this.connected = false;
    this.haVersion = null;
  }

  HAClient.prototype.wsUrl = function () {
    return this.baseUrl.replace(/^http/i, 'ws') + '/api/websocket';
  };

  /** Absolute URL for an HA-relative path like /api/hls/... */
  HAClient.prototype.abs = function (path) {
    return /^https?:\/\//i.test(path) ? path : this.baseUrl + path;
  };

  /** Resolves on auth_ok, rejects on auth_invalid or a failed first connect. */
  HAClient.prototype.connect = function () {
    var self = this;
    return new Promise(function (resolve, reject) {
      var settled = false;
      var ws;
      try {
        ws = new WebSocket(self.wsUrl());
      } catch (e) {
        reject(e);
        return;
      }
      self.ws = ws;

      ws.onmessage = function (ev) {
        var msg;
        try { msg = JSON.parse(ev.data); } catch (e) { return; }
        // HA may coalesce several messages into one JSON array frame.
        (Array.isArray(msg) ? msg : [msg]).forEach(function (m) {
          if (m.type === 'auth_required') {
            ws.send(JSON.stringify({ type: 'auth', access_token: self.token }));
          } else if (m.type === 'auth_ok') {
            self.haVersion = m.ha_version;
            self.connected = true;
            if (!settled) { settled = true; resolve(); }
          } else if (m.type === 'auth_invalid') {
            var err = new Error('Authentication failed: ' + (m.message || 'invalid token'));
            err.fatal = true; // retrying with a bad token is pointless
            if (!settled) { settled = true; reject(err); }
            ws.close();
          } else {
            self.handle(m);
          }
        });
      };

      ws.onclose = function () {
        self.connected = false;
        Object.keys(self.pending).forEach(function (id) {
          self.pending[id].reject(new Error('Connection lost'));
        });
        self.pending = {};
        self.subscriptions = {};
        if (!settled) {
          settled = true;
          reject(new Error('Cannot reach ' + self.wsUrl()));
        }
      };
    });
  };

  HAClient.prototype.close = function () {
    if (this.ws) this.ws.close();
  };

  HAClient.prototype.handle = function (m) {
    if (m.type === 'result') {
      var p = this.pending[m.id];
      if (!p) return;
      delete this.pending[m.id];
      if (m.success) p.resolve(m.result);
      else p.reject(new Error((m.error && m.error.message) || 'Request failed'));
    } else if (m.type === 'event') {
      var cb = this.subscriptions[m.id];
      if (cb) cb(m.event);
    }
  };

  HAClient.prototype.send = function (msg) {
    var self = this;
    if (!self.connected) return Promise.reject(new Error('Not connected to Home Assistant'));
    var id = self.nextId++;
    msg.id = id;
    return new Promise(function (resolve, reject) {
      self.pending[id] = { resolve: resolve, reject: reject };
      self.ws.send(JSON.stringify(msg));
    });
  };

  /**
   * Subscription-style command (subscribe_events, camera/webrtc/offer, ...).
   * Resolves with an unsubscribe function once HA acknowledges it.
   */
  HAClient.prototype.subscribe = function (msg, callback) {
    var self = this;
    if (!self.connected) return Promise.reject(new Error('Not connected to Home Assistant'));
    var id = self.nextId++;
    msg.id = id;
    self.subscriptions[id] = callback;
    return new Promise(function (resolve, reject) {
      self.pending[id] = {
        resolve: function () {
          resolve(function unsubscribe() {
            if (!self.subscriptions[id]) return;
            delete self.subscriptions[id];
            if (self.connected) {
              self.send({ type: 'unsubscribe_events', subscription: id }).catch(function () {});
            }
          });
        },
        reject: function (e) { delete self.subscriptions[id]; reject(e); }
      };
      self.ws.send(JSON.stringify(msg));
    });
  };

  // ---------- convenience wrappers ----------

  HAClient.prototype.friendlyName = function (entityId) {
    return this.send({ type: 'get_states' }).then(function (states) {
      var s = states.filter(function (st) { return st.entity_id === entityId; })[0];
      if (!s) throw new Error(entityId + ' not found in Home Assistant');
      return (s.attributes && s.attributes.friendly_name) || entityId;
    });
  };

  /** [{id, name}] of all camera entities, sorted by name. */
  HAClient.prototype.listCameras = function () {
    return this.send({ type: 'get_states' }).then(function (states) {
      return states
        .filter(function (s) { return s.entity_id.indexOf('camera.') === 0; })
        .map(function (s) {
          return { id: s.entity_id, name: (s.attributes && s.attributes.friendly_name) || s.entity_id };
        })
        .sort(function (a, b) { return a.name.localeCompare(b.name); });
    });
  };

  HAClient.prototype.currentUser = function () {
    return this.send({ type: 'auth/current_user' });
  };

  /** Signed absolute URL for an authenticated HA path (camera_proxy, /media/...). */
  HAClient.prototype.signPath = function (path, expiresSeconds) {
    var self = this;
    return self.send({ type: 'auth/sign_path', path: path, expires: expiresSeconds || 30 })
      .then(function (r) { return self.abs(r.path); });
  };

  HAClient.prototype.snapshotUrl = function (entityId) {
    return this.signPath('/api/camera_proxy/' + entityId, 60);
  };

  HAClient.prototype.mjpegUrl = function (entityId) {
    return this.signPath('/api/camera_proxy_stream/' + entityId, 24 * 3600);
  };

  HAClient.prototype.hlsUrl = function (entityId) {
    var self = this;
    return self.send({ type: 'camera/stream', entity_id: entityId, format: 'hls' })
      .then(function (r) { return self.abs(r.url); });
  };

  HAClient.prototype.webrtcClientConfig = function (entityId) {
    return this.send({ type: 'camera/webrtc/get_client_config', entity_id: entityId })
      .catch(function () { return { configuration: {} }; });
  };

  global.HAClient = HAClient;
})(window);
