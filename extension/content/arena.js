/* Orbit's Arena adapter. It focuses the existing composer and inserts a user-visible prompt. */
(() => {
  const isVisible = (element) => {
    if (!element || element.disabled || element.getAttribute('aria-disabled') === 'true') return false;
    const style = window.getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
  };

  const findInRoot = (root) => {
    const selectors = [
      'textarea:not([disabled])',
      '[contenteditable="true"]',
      '[role="textbox"]',
      'textarea[placeholder*="message" i]',
      'textarea[placeholder*="prompt" i]',
      'textarea[placeholder*="ask" i]',
      'input[type="text"]'
    ];
    for (const selector of selectors) {
      const match = [...root.querySelectorAll(selector)].find(isVisible);
      if (match) return match;
    }
    // Some versions of the app put the composer behind an open shadow root.
    for (const element of root.querySelectorAll('*')) {
      if (element.shadowRoot) {
        const match = findInRoot(element.shadowRoot);
        if (match) return match;
      }
    }
    return null;
  };

  const findComposer = () => findInRoot(document);

  const waitForComposer = async (attempts = 16) => {
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      const element = findComposer();
      if (element) return element;
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
    throw new Error('Arena composer was not found. Open Agent Mode and click the chat box once, then retry.');
  };

  const insertPrompt = async (prompt) => {
    const element = await waitForComposer();
    element.focus();
    if (element.matches('textarea, input')) {
      const prototype = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
      setter?.call(element, prompt);
      if (!setter) element.value = prompt;
      element.dispatchEvent(new Event('input', { bubbles: true }));
      element.dispatchEvent(new Event('change', { bubbles: true }));
    } else {
      // execCommand updates the editing host in React/ProseMirror more reliably
      // than assigning textContent alone.
      document.execCommand('selectAll', false);
      document.execCommand('insertText', false, prompt);
      if (!element.textContent?.includes(prompt.slice(0, 40))) element.textContent = prompt;
      element.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: prompt }));
    }
    element.scrollIntoView({ block: 'center', behavior: 'smooth' });
    return { inserted: true };
  };

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message?.type !== 'orbit:compose-prompt') return undefined;
    insertPrompt(message.prompt)
      .then((result) => sendResponse({ ok: true, ...result }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  });
})();
