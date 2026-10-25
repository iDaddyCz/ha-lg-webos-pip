// Fake Home Assistant for testing the app in a desktop browser.
//   npm run mock   ->  open http://localhost:8124/tv.html
// Implements just the WebSocket commands the app uses, plus camera_proxy,
// camera_proxy_stream (MJPEG) and HLS fed by an ffmpeg test pattern.
import { spawn } from 'node:child_process';
import { createReadStream, existsSync, mkdirSync, readFileSync, rmSync } from 'node:fs';
import { createServer } from 'node:http';
import { dirname, extname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';
import { WebSocketServer } from 'ws';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const appDir = join(root, '.mock/app');
const media = join(root, '.mock/media');
const PORT = 8124;
const CAMERAS = { 'camera.front_door': 'Front Door', 'camera.garden': 'Garden' };

rmSync(media, { recursive: true, force: true });
mkdirSync(media, { recursive: true });

const ffmpeg = spawn('ffmpeg', [
  '-loglevel', 'error', '-re',
  '-f', 'lavfi', '-i', 'testsrc2=size=1280x720:rate=25',
  '-vf', "drawtext=text='%{localtime\\:%T}':fontsize=72:fontcolor=white:box=1:boxcolor=black@0.6:x=40:y=40",
  '-map', '0', '-c:v', 'libx264', '-preset', 'veryfast', '-tune', 'zerolatency', '-g', '25',
  '-f', 'hls', '-hls_time', '1', '-hls_list_size', '6', '-hls_flags', 'delete_segments',
  join(media, 'master_playlist.m3u8'),
  '-map', '0', '-r', '5', '-q:v', '5', '-f', 'image2', '-update', '1', join(media, 'frame.jpg')
], { stdio: ['ignore', 'inherit', 'inherit'] });
process.on('exit', () => ffmpeg.kill());
process.on('SIGINT', () => process.exit());

const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json',
  '.png': 'image/png', '.jpg': 'image/jpeg', '.m3u8': 'application/vnd.apple.mpegurl', '.ts': 'video/mp2t' };

function sendFile(res, file) {
  if (!existsSync(file)) { res.writeHead(404).end(); return; }
  res.writeHead(200, { 'Content-Type': TYPES[extname(file)] || 'application/octet-stream', 'Cache-Control': 'no-store', 'Access-Control-Allow-Origin': '*' });
  createReadStream(file).pipe(res);
}

function signed(url) {
  return url.searchParams.get('authSig') === 'mock';
}

const TV_PAGE = `<!doctype html><title>Mock TV</title>
<style>html,body{margin:0;height:100%;background:#000;overflow:hidden}
#tv{position:absolute;width:1920px;height:1080px;transform-origin:0 0;
background:linear-gradient(135deg,#2a5d8f,#6b3fa0 50%,#c0603a);}
#tv h1{position:absolute;left:80px;bottom:80px;margin:0;font:600 64px sans-serif;color:#fff;opacity:.8}
iframe{position:absolute;inset:0;width:1920px;height:1080px;border:0;background:transparent}</style>
<div id="tv"><h1>Live TV (mock)</h1><iframe id="app" allowtransparency="true"></iframe></div>
<script>
  const tv=document.getElementById('tv');
  const fit=()=>tv.style.transform='scale('+Math.min(innerWidth/1920,innerHeight/1080)+')';
  addEventListener('resize',fit);fit();
  document.getElementById('app').src='/app/index.html'+location.search;
</script>`;

const server = createServer((req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);
  const p = url.pathname;

  if (p === '/' || p === '/tv.html') { res.writeHead(200, { 'Content-Type': 'text/html' }).end(TV_PAGE); return; }
  if (p.startsWith('/app/')) { sendFile(res, join(appDir, normalize(p.slice(5)).replace(/^(\.\.[/\\])+/, ''))); return; }

  const cam = p.match(/^\/api\/camera_proxy(_stream)?\/(camera\.\w+)$/);
  if (cam) {
    if (!signed(url) || !CAMERAS[cam[2]]) { res.writeHead(401).end(); return; }
    if (!cam[1]) { sendFile(res, join(media, 'frame.jpg')); return; }
    res.writeHead(200, { 'Content-Type': 'multipart/x-mixed-replace;boundary=frame', 'Cache-Control': 'no-store' });
    const t = setInterval(() => {
      try {
        const jpg = readFileSync(join(media, 'frame.jpg'));
        res.write(`--frame\r\nContent-Type: image/jpeg\r\nContent-Length: ${jpg.length}\r\n\r\n`);
        res.write(jpg);
        res.write('\r\n');
      } catch { /* frame being rewritten */ }
    }, 200);
    req.on('close', () => clearInterval(t));
    return;
  }

  const hls = p.match(/^\/api\/hls\/mock\/([\w.]+)$/);
  if (hls) { sendFile(res, join(media, hls[1])); return; }

  res.writeHead(404).end();
});

const wss = new WebSocketServer({ server, path: '/api/websocket' });
wss.on('connection', (ws) => {
  let authed = false;
  const send = (m) => ws.send(JSON.stringify(m));
  const result = (id, r) => send({ id, type: 'result', success: true, result: r });
  const fail = (id, message) => send({ id, type: 'result', success: false, error: { code: 'mock', message } });

  send({ type: 'auth_required', ha_version: 'mock' });
  ws.on('message', (raw) => {
    const m = JSON.parse(raw);
    console.log('ws <-', m.type, m.entity_id || m.path || '');
    if (!authed) {
      if (m.type === 'auth' && m.access_token === 'mock-token') { authed = true; send({ type: 'auth_ok', ha_version: 'mock' }); }
      else { send({ type: 'auth_invalid', message: 'bad token' }); ws.close(); }
      return;
    }
    switch (m.type) {
      case 'get_states':
        return result(m.id, Object.entries(CAMERAS).map(([entity_id, friendly_name]) =>
          ({ entity_id, state: 'idle', attributes: { friendly_name } })));
      case 'auth/current_user':
        return result(m.id, { id: 'mock', name: 'Mock User', is_admin: true });
      case 'auth/sign_path':
        return result(m.id, { path: m.path + (m.path.includes('?') ? '&' : '?') + 'authSig=mock' });
      case 'camera/stream':
        return result(m.id, { url: '/api/hls/mock/master_playlist.m3u8' });
      case 'camera/webrtc/get_client_config':
        return result(m.id, { configuration: {} });
      case 'camera/webrtc/offer':
        result(m.id, null);
        return send({ id: m.id, type: 'event', event: { type: 'error', code: 'mock', message: 'mock HA has no WebRTC' } });
      case 'unsubscribe_events':
        return result(m.id, null);
      default:
        return fail(m.id, 'unknown command ' + m.type);
    }
  });
});

server.listen(PORT, () => console.log(`mock HA on http://localhost:${PORT}  ->  open /tv.html (?camera=...&mode=...)`));
