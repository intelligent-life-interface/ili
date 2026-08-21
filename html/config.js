// ─── Server-Konfiguration ────────────────────────────────────────────────────
// IPs anpassen: SMARTHOME = Server auf dem das Dashboard läuft,
// OLLAMA = Server mit der Ollama-Instanz (kann identisch sein).
// Werden über window.DASHBOARD_CONFIG überschrieben falls das Backend
// /api/client-config liefert; ansonsten Fallback auf diese Defaults.
const _cfgOverride = (typeof window.DASHBOARD_CONFIG !== 'undefined') ? window.DASHBOARD_CONFIG : {};
const CONFIG = {
  SMARTHOME: _cfgOverride.smarthome_ip || window.location.hostname,
  OLLAMA:    _cfgOverride.ollama_ip    || window.location.hostname,
  DEV:       window.location.hostname,  // Dev Server (auto: immer dieser Server)
};

// Ports die auf dem DEV-Server laufen (nicht Smart Home)
const DEV_PORTS = new Set([
  80, 3001, 3002, 3003, 3004, 3010, 5678,
  8000, 8085, 8088, 8090, 8091, 8096, 8097, 8200,
  8443, 8445, 8855, 8888, 8889, 8978, 9090,
]);

// Ports die immer auf dem SMARTHOME-Server bleiben
const SMARTHOME_PORTS = new Set([
  8083, 8079, 8081, 8086, 3000, 8123, 1884,
]);

// ─── IP-Ersetzung nach DOM-Load ──────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  const OLD_IP = CONFIG.SMARTHOME;

  if (CONFIG.DEV === OLD_IP) {
    console.debug("[config.js] DEV === SMARTHOME, keine Ersetzung nötig");
    return;
  }

  // Alle Links durchgehen
  document.querySelectorAll('a[href]').forEach(a => {
    try {
      const url = new URL(a.href);
      const port = parseInt(url.port) || (url.protocol === 'https:' ? 443 : 80);

      if (url.hostname === OLD_IP && DEV_PORTS.has(port)) {
        url.hostname = CONFIG.DEV;
        a.href = url.toString();
        // Text im Link auch ersetzen
        if (a.textContent.includes(OLD_IP)) {
          a.textContent = a.textContent.replaceAll(OLD_IP, CONFIG.DEV);
        }
      }
    } catch (e) { /* relative URLs überspringen */ }
  });

  // card-url Divs (enthalten oft auch Text mit der IP)
  document.querySelectorAll('.card-url').forEach(div => {
    DEV_PORTS.forEach(port => {
      const pattern = `${OLD_IP}:${port}`;
      if (div.innerHTML.includes(pattern)) {
        div.innerHTML = div.innerHTML.replaceAll(pattern, `${CONFIG.DEV}:${port}`);
      }
    });
  });

  console.debug(`[config.js] DEV-Links → ${CONFIG.DEV}, SMARTHOME → ${CONFIG.SMARTHOME}`);
});
