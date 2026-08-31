/* Orbit's Arena adapter. It focuses the existing composer and inserts a user-visible prompt. */
(() => {
  const composer = () => document.querySelector('textarea:not([disabled]), [contenteditable="true"]');

  const insertPrompt = (prompt) => {
    const element = composer();
    if (!element) throw new Error('Arena composer was not found. Click into the chat box once, then retry.');
    element.focus();
    if (element.matches('textarea, input')) {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set;
      setter?.call(element, prompt);
      if (!setter) element.value = prompt;
      element.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: prompt }));
    } else {
      element.textContent = prompt;
      element.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: prompt }));
    }
    element.scrollIntoView({ block: 'center', behavior: 'smooth' });
    return { inserted: true };
  };

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message?.type !== 'orbit:compose-prompt') return;
    try {
      sendResponse({ ok: true, ...insertPrompt(message.prompt) });
    } catch (error) {
      sendResponse({ ok: false, error: error.message });
    }
  });
})();
