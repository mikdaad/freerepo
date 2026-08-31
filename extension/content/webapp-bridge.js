/* Relays explicit actions from the Orbit dashboard to the extension service worker. */
(() => {
  const allowed = new Set(['orbit:sync', 'orbit:handoff']);
  window.addEventListener('message', (event) => {
    if (event.source !== window || event.data?.source !== 'orbit-app' || !allowed.has(event.data.type)) return;
    chrome.runtime.sendMessage({ source: 'orbit-app', ...event.data }, (response) => {
      window.postMessage({ source: 'orbit-extension', request: event.data.type, ...response }, '*');
    });
  });
})();
