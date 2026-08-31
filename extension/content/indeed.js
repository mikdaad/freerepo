/* Orbit's Indeed adapter. It only reads the visible job page; credentials remain in Indeed. */
(() => {
  const firstText = (selectors) => {
    for (const selector of selectors) {
      const element = document.querySelector(selector);
      if (element?.innerText?.trim()) return element.innerText.trim();
    }
    return '';
  };

  const extractJob = () => {
    const title = firstText([
      '[data-testid="jobsearch-JobInfoHeader-title"]',
      '[data-testid="jobsearch-JobInfoHeader-title"] h1',
      '.jobsearch-JobInfoHeader-title',
      'h1'
    ]);
    const company = firstText([
      '[data-testid="inlineHeader-companyName"]',
      '[data-testid="companyName"]',
      '.jobsearch-InlineCompanyRating a',
      '.jobsearch-JobInfoHeader-subtitle a'
    ]);
    const location = firstText([
      '[data-testid="inlineHeader-companyLocation"]',
      '[data-testid="job-location"]',
      '.jobsearch-JobInfoHeader-subtitle div'
    ]);
    const description = firstText([
      '#jobDescriptionText',
      '[data-testid="jobDescription"]',
      '.jobsearch-jobDescriptionText'
    ]);

    if (!title && !description) {
      throw new Error('No job description found. Open an individual Indeed job page and try again.');
    }
    return {
      title: title || 'Untitled role',
      company: company || 'Unknown employer',
      location: location || 'Location not listed',
      description,
      source: 'Indeed',
      url: window.location.href,
      capturedAt: new Date().toISOString()
    };
  };

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message?.type !== 'orbit:extract-job') return;
    try {
      sendResponse({ ok: true, ...extractJob() });
    } catch (error) {
      sendResponse({ ok: false, error: error.message });
    }
  });
})();
