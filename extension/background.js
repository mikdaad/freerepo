const INDEED_HOSTS = ['indeed.com', 'indeed.co.uk', 'indeed.ae', 'indeed.ca', 'indeed.com.au'];
const APP_MESSAGE_SOURCE = 'orbit-app';

function isIndeed(url = '') {
  try {
    const host = new URL(url).hostname.replace(/^www\./, '');
    return INDEED_HOSTS.some((domain) => host === domain || host.endsWith(`.${domain}`));
  } catch {
    return false;
  }
}

async function findTab(predicate) {
  const tabs = await chrome.tabs.query({});
  return tabs.find((tab) => predicate(tab.url || ''));
}

async function captureIndeed() {
  const tab = await findTab(isIndeed);
  if (!tab?.id) throw new Error('Open the Indeed job page you want to capture first.');
  return chrome.tabs.sendMessage(tab.id, { type: 'orbit:extract-job' });
}

async function handoffToArena(prompt) {
  const tab = await findTab((url) => url.startsWith('https://arena.ai/'));
  if (!tab?.id) throw new Error('Open your Arena.ai session in another tab first.');
  await chrome.tabs.update(tab.id, { active: true });
  await chrome.windows.update(tab.windowId, { focused: true });
  return chrome.tabs.sendMessage(tab.id, { type: 'orbit:compose-prompt', prompt });
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.source !== APP_MESSAGE_SOURCE && message?.source !== 'orbit-bridge') return undefined;

  (async () => {
    if (message.type === 'orbit:sync') {
      const job = await captureIndeed();
      await chrome.storage.local.set({ lastCapturedJob: job, capturedAt: Date.now() });
      sendResponse({ ok: true, type: 'orbit:job-captured', job });
      return;
    }
    if (message.type === 'orbit:handoff') {
      const result = await handoffToArena(message.prompt);
      sendResponse({ ok: true, type: 'orbit:arena-ready', result });
      return;
    }
    sendResponse({ ok: false, error: 'Unknown Orbit connector message.' });
  })().catch((error) => sendResponse({ ok: false, error: error.message }));

  return true;
});
