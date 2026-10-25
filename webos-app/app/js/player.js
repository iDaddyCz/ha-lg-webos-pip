/*
 * Renders one feed into the PIP box.
 *
 * Modes:
 *   mjpeg    - HA camera_proxy_stream in an <img>. Default: drawn on the graphics
 *              plane, so it doesn't compete with live TV for the hardware video decoder.
 *   snapshot - polls HA camera_proxy stills. Slowest, but works with every camera.
 *   hls      - HA camera/stream (LL-HLS) in a <video>, via hls.js or native playback.
 *   webrtc   - HA camera/webrtc/offer (HA 2024.11+, go2rtc) in a <video>.
 *   url      - any URL: .m3u8 -> hls, mjpeg-looking -> <img>, otherwise <video>.
 *              HA paths ("/media/local/x.mp4") are signed automatically.
 *
 * <video> modes need a second hardware decoder while the TV is playing something
 * else; whether webOS allows that in an overlay window depends on the model.
 */
(function (global) {
  'use strict';

  var FIRST_FRAME_TIMEOUT = 15000;

  function Player(videoEl, imgEl, onState) {
    this.video = videoEl;
    this.img = imgEl;
    this.onState = onState || function () {};
    this.gen = 0;          // bumped on every stop(); stale async work checks it
    this.cleanup = [];
  }

  Player.prototype.stop = function () {
    this.gen++;
    this.cleanup.forEach(function (fn) { try { fn(); } catch (e) { /* ignore */ } });
    this.cleanup = [];
    this.video.pause();
    this.video.removeAttribute('src');
    this.video.srcObject = null;
    this.video.load();
    this.img.removeAttribute('src');
    this.video.classList.add('hidden');
    this.img.classList.add('hidden');
  };

  /** source: {camera, url, mode}. Resolves once the first frame is on screen. */
  Player.prototype.play = function (ha, source) {
    var self = this;
    self.stop();
    var gen = self.gen;
    var mode = source.mode || 'mjpeg';
    self.onState('loading');

    var started;
    if (source.url) started = self.playUrl(ha, source.url, gen);
    else if (mode === 'snapshot') started = self.playSnapshots(ha, source.camera, source.refresh, gen);
    else if (mode === 'hls') started = ha.hlsUrl(source.camera).then(function (u) { return self.playHls(u, gen); });
    else if (mode === 'webrtc') started = self.playWebRtc(ha, source.camera, gen);
    else started = ha.mjpegUrl(source.camera).then(function (u) { return self.playImage(u, gen); });

    return withTimeout(started, FIRST_FRAME_TIMEOUT, 'No picture from ' + (source.camera || source.url) + ' (' + mode + ')')
      .then(function () {
        if (gen !== self.gen) return;
        var usingImg = !self.img.classList.contains('hidden');
        self.onState('playing', {
          mode: mode,
          width: usingImg ? self.img.naturalWidth : self.video.videoWidth,
          height: usingImg ? self.img.naturalHeight : self.video.videoHeight
        });
      }, function (err) {
        if (gen === self.gen) {
          self.stop();
          self.onState('error', err.message || String(err));
        }
        throw err;
      });
  };

  Player.prototype.playUrl = function (ha, url, gen) {
    var self = this;
    var resolved = url.charAt(0) === '/' ? ha.signPath(url, 24 * 3600) : Promise.resolve(url);
    return resolved.then(function (u) {
      if (/\.m3u8(\?|$)/i.test(u)) return self.playHls(u, gen);
      if (/mjpe?g|camera_proxy_stream|action=stream|\.cgi/i.test(u)) return self.playImage(u, gen);
      if (/\.(jpe?g|png|gif|webp)(\?|$)/i.test(u)) return self.playImage(u, gen);
      return self.playVideo(u, gen);
    });
  };

  // ---------- <img> based ----------

  Player.prototype.playImage = function (url, gen) {
    var self = this;
    return new Promise(function (resolve, reject) {
      if (gen !== self.gen) return;
      var img = self.img;
      img.onerror = function () { reject(new Error('Image stream failed to load')); };
      img.src = url;
      img.classList.remove('hidden');
      // Multipart MJPEG doesn't reliably fire "load"; watch for the first decoded frame instead.
      var timer = setInterval(function () {
        if (gen !== self.gen) { clearInterval(timer); return; }
        if (img.naturalWidth > 0) { clearInterval(timer); resolve(); }
      }, 100);
      self.cleanup.push(function () { clearInterval(timer); img.onerror = null; });
    });
  };

  Player.prototype.playSnapshots = function (ha, entityId, refreshMs, gen) {
    var self = this;
    var interval = Math.max(200, refreshMs || 500);
    return new Promise(function (resolve, reject) {
      var failures = 0;
      var timer = null;
      self.cleanup.push(function () { clearTimeout(timer); });

      function next() {
        if (gen !== self.gen) return;
        // Every frame gets a fresh signature: HA signs the query string too,
        // so a cache-busting parameter would invalidate a reused one.
        ha.snapshotUrl(entityId).then(function (url) {
          var pre = new Image();
          pre.onload = function () {
            if (gen !== self.gen) return;
            failures = 0;
            self.img.src = url;
            self.img.classList.remove('hidden');
            resolve();
            timer = setTimeout(next, interval);
          };
          pre.onerror = fail;
          pre.src = url;
        }, fail);
      }
      function fail() {
        if (gen !== self.gen) return;
        if (++failures >= 5) reject(new Error('Snapshots from ' + entityId + ' keep failing'));
        else timer = setTimeout(next, interval * 2);
      }
      next();
    });
  };

  // ---------- <video> based ----------

  Player.prototype.showVideo = function (gen) {
    var self = this;
    var v = self.video;
    v.classList.remove('hidden');
    return new Promise(function (resolve, reject) {
      function onPlaying() { resolve(); }
      function onError() { reject(new Error('Video error ' + (v.error ? v.error.code : ''))); }
      v.addEventListener('playing', onPlaying);
      v.addEventListener('error', onError);
      self.cleanup.push(function () {
        v.removeEventListener('playing', onPlaying);
        v.removeEventListener('error', onError);
      });
      playWithAutoplayFallback(v).catch(reject);
    });
  };

  Player.prototype.playVideo = function (url, gen) {
    if (gen !== this.gen) return Promise.reject(new Error('cancelled'));
    this.video.loop = true;
    this.video.src = url;
    return this.showVideo(gen);
  };

  Player.prototype.playHls = function (url, gen) {
    var self = this;
    if (gen !== self.gen) return Promise.reject(new Error('cancelled'));
    var v = self.video;
    v.loop = false;
    if (global.Hls && global.Hls.isSupported()) {
      var hls = new global.Hls({
        lowLatencyMode: true,
        backBufferLength: 10,
        liveSyncDurationCount: 2,
        maxLiveSyncPlaybackRate: 1.5,
        manifestLoadingTimeOut: 15000,
        levelLoadingTimeOut: 15000,
        fragLoadingTimeOut: 15000
      });
      self.cleanup.push(function () { hls.destroy(); });
      var fatal = new Promise(function (_, reject) {
        hls.on(global.Hls.Events.ERROR, function (_e, data) {
          if (data.fatal) reject(new Error('HLS ' + data.type + ': ' + data.details));
        });
      });
      hls.loadSource(url);
      hls.attachMedia(v);
      return Promise.race([self.showVideo(gen), fatal]);
    }
    v.src = url; // webOS media pipeline plays HLS natively
    return self.showVideo(gen);
  };

  Player.prototype.playWebRtc = function (ha, entityId, gen) {
    var self = this;
    if (!global.RTCPeerConnection) return Promise.reject(new Error('WebRTC is not supported on this TV'));

    return ha.webrtcClientConfig(entityId).then(function (clientConfig) {
      if (gen !== self.gen) throw new Error('cancelled');
      var pc = new RTCPeerConnection(clientConfig.configuration || {});
      var sessionId = null;
      var queued = [];
      var unsubscribe = null;
      self.cleanup.push(function () {
        if (unsubscribe) unsubscribe();
        pc.close();
      });

      if (clientConfig.dataChannel) pc.createDataChannel(clientConfig.dataChannel);
      pc.addTransceiver('video', { direction: 'recvonly' });
      pc.addTransceiver('audio', { direction: 'recvonly' });

      var stream = new MediaStream();
      pc.ontrack = function (e) {
        stream.addTrack(e.track);
        if (self.video.srcObject !== stream) self.video.srcObject = stream;
      };

      function sendCandidate(c) {
        ha.send({
          type: 'camera/webrtc/candidate',
          entity_id: entityId,
          session_id: sessionId,
          candidate: { candidate: c.candidate, sdpMid: c.sdpMid, sdpMLineIndex: c.sdpMLineIndex }
        }).catch(function () {});
      }
      pc.onicecandidate = function (e) {
        if (!e.candidate) return;
        if (sessionId) sendCandidate(e.candidate);
        else queued.push(e.candidate);
      };

      var failed = new Promise(function (_, reject) {
        pc.onconnectionstatechange = function () {
          if (pc.connectionState === 'failed') reject(new Error('WebRTC connection failed'));
        };

        pc.createOffer().then(function (offer) {
          return pc.setLocalDescription(offer).then(function () {
            return ha.subscribe({ type: 'camera/webrtc/offer', entity_id: entityId, offer: offer.sdp }, function (ev) {
              if (ev.type === 'session') {
                sessionId = ev.session_id;
                queued.forEach(sendCandidate);
                queued = [];
              } else if (ev.type === 'answer') {
                pc.setRemoteDescription({ type: 'answer', sdp: ev.answer }).catch(reject);
              } else if (ev.type === 'candidate') {
                var c = typeof ev.candidate === 'string' ? { candidate: ev.candidate, sdpMLineIndex: 0 } : ev.candidate;
                pc.addIceCandidate(c).catch(function () {});
              } else if (ev.type === 'error') {
                reject(new Error('WebRTC: ' + (ev.message || ev.code)));
              }
            });
          });
        }).then(function (unsub) {
          if (gen !== self.gen) unsub();
          else unsubscribe = unsub;
        }).catch(reject);
      });

      return Promise.race([self.showVideo(gen), failed]);
    });
  };

  // ---------- helpers ----------

  function playWithAutoplayFallback(v) {
    var p = v.play();
    if (!p || !p.catch) return Promise.resolve();
    return p.catch(function (e) {
      if (e && e.name === 'NotAllowedError' && !v.muted) {
        v.muted = true;
        return v.play();
      }
      if (e && e.name === 'AbortError') return; // superseded by a newer load
      throw e;
    });
  }

  function withTimeout(promise, ms, message) {
    return new Promise(function (resolve, reject) {
      var t = setTimeout(function () { reject(new Error(message)); }, ms);
      promise.then(function (v) { clearTimeout(t); resolve(v); }, function (e) { clearTimeout(t); reject(e); });
    });
  }

  global.Player = Player;
})(window);
