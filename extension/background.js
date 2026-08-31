const INDEED_HOSTS = ['indeed.com', 'indeed.co.uk', 'indeed.ae', 'indeed.ca', 'indeed.com.au'];
const ARENA_HOSTS = ['arena.ai', 'lmarena.ai'];
const APP_MESSAGE_SOURCE = 'orbit-app';

function hostMatches(url, domains) {
  try {
    const host = new URL(url).hostname.replace(/^www\./, '');
    return domains.some((domain) => host === domain || host.endsWith(`.${domain}`));
  } catch {
    return false;
  }
}

function isIndeed(url = '') { return hostMatches(url, INDEED_HOSTS); }
function isArena(url = '') { return hostMatches(url, ARENA_HOSTS); }
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function findTab(predicate) {
  const tabs = await chrome.tabs.query({});
  // Prefer the active matching tab. It avoids handing off to an old Arena
  // leaderboard tab when the user has a chat open in another window.
  return tabs.find((tab) => tab.active && predicate(tab.url || '')) || tabs.find((tab) => predicate(tab.url || ''));
}

async function sendToArena(tabId, prompt) {
  let lastError;
  // The Arena app is client-rendered. Retry while its composer mounts instead
  // of reporting success as soon as the tab receives focus.
  for (let attempt = 0; attempt < 18; attempt += 1) {
    try {
      const response = await chrome.tabs.sendMessage(tabId, { type: 'orbit:compose-prompt', prompt });
      if (response?.ok) return response;
      lastError = new Error(response?.error || 'Arena could not accept the prompt.');
    } catch (error) {
      lastError = error;
    }
    await pause(500);
  }
  throw lastError || new Error('Arena composer was not available.');
}

async function captureIndeed() {
  const tab = await findTab(isIndeed);
  if (!tab?.id) throw new Error('Open the Indeed job page you want to capture first.');
  try {
    return await chrome.tabs.sendMessage(tab.id, { type: 'orbit:extract-job' });
  } catch {
    throw new Error('Indeed is still loading. Refresh the job page, then try Sync again.');
  }
}

async function handoffToArena(prompt) {
  let tab = await findTab(isArena);
  if (!tab?.id) tab = await chrome.tabs.create({ url: 'https://arena.ai/agent', active: true });
  await chrome.tabs.update(tab.id, { active: true });
  if (tab.windowId) await chrome.windows.update(tab.windowId, { focused: true });
  const result = await sendToArena(tab.id, prompt);
  return { ...result, tabId: tab.id };
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
