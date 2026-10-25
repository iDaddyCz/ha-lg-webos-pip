// Checks .env against the real Home Assistant before installing on the TV:
// token, camera entity, and that an MJPEG stream URL can be signed and returns data.
//   node scripts/check-ha.mjs
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import WebSocket from 'ws';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const env = Object.fromEntries(readFileSync(join(root, '.env'), 'utf8').split(/\r?\n/)
  .map((l) => l.match(/^\s*([A-Z_]+)\s*=\s*(.*?)\s*$/)).filter(Boolean)
  .map((m) => [m[1], m[2].replace(/^(['"])(.*)\1$/, '$2')]));

const base = (env.HA_URL || '').replace(/\/+$/, '');
const camera = env.HA_CAMERA;
if (!base || !env.HA_TOKEN || !camera) {
  console.error('HA_URL, HA_TOKEN and HA_CAMERA must be set in .env');
  process.exit(1);
}

const ws = new WebSocket(base.replace(/^http/, 'ws') + '/api/websocket');
let id = 0;
const pending = new Map();
const call = (msg) => new Promise((resolve, reject) => {
  msg.id = ++id;
  pending.set(msg.id, { resolve, reject });
  ws.send(JSON.stringify(msg));
});

ws.on('error', (e) => { console.error('cannot connect:', e.message); process.exit(1); });
ws.on('message', async (raw) => {
  const m = JSON.parse(raw);
  if (m.type === 'auth_required') return ws.send(JSON.stringify({ type: 'auth', access_token: env.HA_TOKEN }));
  if (m.type === 'auth_invalid') { console.error('token rejected:', m.message); process.exit(1); }
  if (m.type === 'result') {
    const p = pending.get(m.id);
    pending.delete(m.id);
    return m.success ? p.resolve(m.result) : p.reject(new Error(m.error?.message));
  }
  if (m.type !== 'auth_ok') return;

  console.log(`auth ok (HA ${m.ha_version})`);
  try {
    const states = await call({ type: 'get_states' });
    const cams = states.filter((s) => s.entity_id.startsWith('camera.'));
    const cam = cams.find((s) => s.entity_id === camera);
    if (!cam) {
      console.error(`${camera} not found. Cameras: ${cams.map((s) => s.entity_id).join(', ') || 'none'}`);
      process.exit(1);
    }
    console.log(`camera ok: ${camera} "${cam.attributes.friendly_name}" state=${cam.state}`);

    const caps = await call({ type: 'camera/capabilities', entity_id: camera }).catch(() => null);
    if (caps) console.log('stream types:', caps.frontend_stream_types.join(', ') || 'none (mjpeg/snapshot only)');

    const { path } = await call({ type: 'auth/sign_path', path: `/api/camera_proxy_stream/${camera}`, expires: 30 });
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 10000);
    const res = await fetch(base + path, { signal: ctrl.signal });
    const reader = res.body.getReader();
    const { value } = await reader.read();
    clearTimeout(t);
    ctrl.abort();
    console.log(`mjpeg ok: HTTP ${res.status}, ${res.headers.get('content-type')}, first chunk ${value?.length ?? 0} bytes`);
    process.exit(0);
  } catch (e) {
    console.error('failed:', e.message);
    process.exit(1);
  }
});
