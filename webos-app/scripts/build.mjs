// Assembles the installable app: app/ + hls.js + config.js.
//   node scripts/build.mjs           -> build/        (optional .env values baked in as defaults)
//   node scripts/build.mjs --mock    -> .mock/app/    (points at scripts/mock-ha.mjs)
//
// Everything in .env is optional: without it the TV is set up from the app's
// setup screen or from the Home Assistant integration.
import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const mock = process.argv.includes('--mock');
const out = join(root, mock ? '.mock/app' : 'build');

function readEnv(file) {
  if (!existsSync(file)) return {};
  const env = {};
  for (const line of readFileSync(file, 'utf8').split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*?)\s*$/);
    if (m) env[m[1]] = m[2].replace(/^(['"])(.*)\1$/, '$2');
  }
  return env;
}

const env = mock
  ? { HA_URL: 'http://localhost:8124', HA_TOKEN: 'mock-token', HA_CAMERA: 'camera.front_door', HA_TIMEOUT: '0' }
  : { ...readEnv(join(root, '.env')), ...process.env };

// Only values that are actually set, so settings saved on the TV take over.
const config = Object.fromEntries(Object.entries({
  url: (env.HA_URL || '').replace(/\/+$/, ''),
  token: env.HA_TOKEN,
  camera: env.HA_CAMERA,
  mode: env.HA_MODE,
  position: env.HA_POSITION,
  size: env.HA_SIZE && Number(env.HA_SIZE),
  timeout: env.HA_TIMEOUT && Number(env.HA_TIMEOUT)
}).filter(([, v]) => v !== undefined && v !== ''));

const appinfo = JSON.parse(readFileSync(join(root, 'app/appinfo.json'), 'utf8'));

rmSync(out, { recursive: true, force: true });
mkdirSync(out, { recursive: true });
cpSync(join(root, 'app'), out, { recursive: true });
mkdirSync(join(out, 'lib'), { recursive: true });
cpSync(join(root, 'node_modules/hls.js/dist/hls.min.js'), join(out, 'lib/hls.min.js'));
writeFileSync(join(out, 'config.js'),
  `window.APP_INFO = ${JSON.stringify({ id: appinfo.id, title: appinfo.title, version: appinfo.version })};\n` +
  `window.HA_CONFIG = ${JSON.stringify(config, null, 2)};\n`);

console.log(`built ${out}${mock ? ' (mock)' : ''}${config.token ? ' with a baked-in token' : ''}`);
