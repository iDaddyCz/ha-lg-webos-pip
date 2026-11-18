/*
 * Window modes for a resident PIP app.
 *
 * Launching any app makes webOS stop the app in front: YouTube, for one,
 * unloads its video and leaves a black screen. Relaunching an app that is
 * already running doesn't. So HA PIP is a card app that stays running in the
 * background and draws the PIP in a passive floating window that never takes
 * the remote. The setup screen switches back to a normal, focused window.
 *
 * These window properties are private webOS APIs; they work without root.
 */
(function (global) {
  'use strict';

  var sys = global.webOSSystem || global.PalmSystem || null;
  var timers = [];

  function apply(passive) {
    if (!sys) return;
    try {
      if (sys.setWindowProperty) {
        sys.setWindowProperty('_WEBOS_WINDOW_TYPE', passive ? '_WEBOS_WINDOW_TYPE_FLOATING' : '_WEBOS_WINDOW_TYPE_CARD');
        sys.setWindowProperty('needFocus', passive ? 'false' : 'true');
      }
      if (sys.setInputRegion) {
        sys.setInputRegion([{ x: 0, y: 0, width: passive ? 0 : 1920, height: passive ? 0 : 1080 }]);
      }
      if (sys.keepAlive) sys.keepAlive(true);
    } catch (e) {
      // Firmware without these properties: the PIP still works, it just takes the remote.
    }
  }

  function clearTimers() {
    timers.forEach(clearTimeout);
    timers = [];
  }

  global.AppWindow = {
    /** Draw without taking focus or remote input, so the app in front keeps playing. */
    passive: function () {
      clearTimers();
      apply(true);
      // Creating or raising the native window can take focus back.
      [60, 300, 1000].forEach(function (ms) {
        timers.push(setTimeout(function () { apply(true); }, ms));
      });
    },
    /** A normal window that takes the remote (setup screen, preview). */
    interactive: function () {
      clearTimers();
      apply(false);
      if (sys && sys.activate) sys.activate();
    }
  };

  // Every launch starts passive (this runs before the rest of the app loads);
  // the setup screen switches to interactive itself.
  global.AppWindow.passive();
})(window);
