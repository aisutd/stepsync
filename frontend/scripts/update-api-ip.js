#!/usr/bin/env node
// Points EXPO_PUBLIC_API_URL in frontend/.env at this computer's current local IP,
// so the phone can reach the backend after Wi-Fi hands out a new address.
// Runs automatically before `npm start`. Leaves the line alone when it is
// commented out (mock mode) or points somewhere else on purpose (an https tunnel).
// If it picks the wrong network, force one: API_IP=192.168.1.20 npm start

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

const ip = process.env.API_IP?.trim() || localIp();
if (!ip) {
  console.log('[api-ip] No network connection found; leaving .env unchanged.');
  process.exit(0);
}
const url = `http://${ip}:${PORT}`;
const line = `EXPO_PUBLIC_API_URL=${url}`;

let text = fs.existsSync(envPath) ? fs.readFileSync(envPath, 'utf8') : '';
const active = /^EXPO_PUBLIC_API_URL=(.*)$/m.exec(text);
const commented = /^\s*#\s*EXPO_PUBLIC_API_URL=/m.test(text);

if (active) {
  const current = active[1].trim();
  // Only rewrite plain local addresses like http://10.x.x.x:8000, never a tunnel or other URL.
  if (!/^http:\/\/\d{1,3}(\.\d{1,3}){3}(:\d+)?\/?$/.test(current)) {
    console.log(`[api-ip] Keeping EXPO_PUBLIC_API_URL=${current} (not a local IP address).`);
    process.exit(0);
  }
  if (current === url) {
    console.log(`[api-ip] Backend address is up to date: ${url}`);
    process.exit(0);
  }
  text = text.replace(/^EXPO_PUBLIC_API_URL=.*$/m, line);
  fs.writeFileSync(envPath, text);
  console.log(`[api-ip] Updated backend address: ${current} -> ${url}`);
} else if (commented) {
  console.log('[api-ip] EXPO_PUBLIC_API_URL is commented out (mock mode); leaving it.');
} else {
  text = text + (text && !text.endsWith('\n') ? '\n' : '') + line + '\n';
  fs.writeFileSync(envPath, text);
  console.log(`[api-ip] Added backend address: ${url}`);
}
