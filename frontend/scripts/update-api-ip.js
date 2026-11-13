#!/usr/bin/env node
// Points EXPO_PUBLIC_API_URL in frontend/.env at this computer's current local IP,
// so the phone can reach the backend after Wi-Fi hands out a new address.
// Runs automatically before `npm start`. Leaves the line alone when it is
// commented out (mock mode) or points at a real server you set on purpose.
// A leftover tunnel address (trycloudflare, ngrok, localtunnel) is switched back to the local IP.
// If it picks the wrong network, force one: API_IP=192.168.1.20 npm start
// To use a backend tunnel instead: API_URL=https://xyz.trycloudflare.com npm run tunnel

const fs = require('fs');
const os = require('os');
const path = require('path');

const PORT = 8000;
const envPath = path.join(__dirname, '..', '.env');

function localIp() {
  const interfaces = os.networkInterfaces();
  const candidates = [];
  for (const [name, addresses] of Object.entries(interfaces)) {
    for (const a of addresses ?? []) {
      if (a.family !== 'IPv4' && a.family !== 4) continue;
      if (a.internal || a.address.startsWith('169.254.')) continue; // loopback, no-DHCP fallback
      candidates.push({ name, address: a.address });
    }
  }
  // Prefer the Mac's Wi-Fi/Ethernet (en0, en1...), then any private-range address.
  const isPrivate = (ip) => /^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(ip);
  candidates.sort((x, y) => {
    const score = (c) => (c.name.startsWith('en') ? 0 : 2) + (isPrivate(c.address) ? 0 : 1);
    return score(x) - score(y) || x.name.localeCompare(y.name);
  });
  return candidates[0]?.address ?? null;
}

// Tunnel mode: API_URL is the backend's public tunnel address, written as is.
const tunnelUrl = process.env.API_URL?.trim().replace(/\/+$/, '');
if (tunnelUrl) {
  if (!/^https?:\/\/\S+$/.test(tunnelUrl)) {
    console.error(`[api-ip] API_URL must be a full address like https://xyz.trycloudflare.com (got "${tunnelUrl}").`);
    process.exit(1);
  }
  writeApiUrl(tunnelUrl, 'tunnel');
  process.exit(0);
}

const ip = process.env.API_IP?.trim() || localIp();
if (!ip) {
  console.log('[api-ip] No network connection found; leaving .env unchanged.');
  process.exit(0);
}
writeApiUrl(`http://${ip}:${PORT}`, 'local');

/** Put url in .env as EXPO_PUBLIC_API_URL. In local mode, only replace local IPs and old tunnels. */
function writeApiUrl(url, mode) {
  const line = `EXPO_PUBLIC_API_URL=${url}`;
  let text = fs.existsSync(envPath) ? fs.readFileSync(envPath, 'utf8') : '';
  const active = /^EXPO_PUBLIC_API_URL=(.*)$/m.exec(text);
  const commented = /^\s*#\s*EXPO_PUBLIC_API_URL=/m.test(text);

  if (active) {
    const current = active[1].trim();
    const localAddress = /^http:\/\/\d{1,3}(\.\d{1,3}){3}(:\d+)?\/?$/.test(current);
    const oldTunnel = /^https?:\/\/[^/]*(trycloudflare\.com|ngrok-free\.app|ngrok\.app|ngrok\.io|ngrok-free\.dev|loca\.lt)(\/|$)/.test(current);
    if (mode === 'local' && !localAddress && !oldTunnel) {
      console.log(`[api-ip] Keeping EXPO_PUBLIC_API_URL=${current} (not a local IP or tunnel address).`);
      return;
    }
    if (current === url) {
      console.log(`[api-ip] Backend address is up to date: ${url}`);
      return;
    }
    text = text.replace(/^EXPO_PUBLIC_API_URL=.*$/m, line);
    fs.writeFileSync(envPath, text);
    console.log(`[api-ip] Updated backend address: ${current} -> ${url}`);
  } else if (commented && mode === 'local') {
    console.log('[api-ip] EXPO_PUBLIC_API_URL is commented out (mock mode); leaving it.');
  } else {
    text = text + (text && !text.endsWith('\n') ? '\n' : '') + line + '\n';
    fs.writeFileSync(envPath, text);
    console.log(`[api-ip] Added backend address: ${url}`);
  }
}
