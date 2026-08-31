# Orbit browser connector

This optional Manifest V3 extension connects the Orbit dashboard to tabs you are already signed into. It reads the visible job description from Indeed, focuses your existing Arena.ai tab, and inserts the tailored prompt into its composer. It never asks for or stores your Indeed or Arena credentials.

## Install locally

1. Run the dashboard from the repository root with `npm run dev`.
2. Open `chrome://extensions`, enable **Developer mode**, choose **Load unpacked**, and select this `extension` directory.
3. Keep Orbit open at the local Vite URL (or the deployed Orbit preview), an individual Indeed job page, and your existing Arena.ai session.
4. In Orbit, click **Sync Indeed jobs**. Open a role, then choose **Send the brief to your open Arena.ai session**.

## Guardrails

- The adapter only reads the visible Indeed job page; it does not access passwords, cookies, or private APIs.
- Arena handoff inserts text into the existing composer but does not press Send.
- Upload and Submit remain explicit user actions. The dashboard's Safe mode should remain enabled for real applications.
- Indeed markup changes frequently. If a selector stops working, update `content/indeed.js` rather than bypassing the site or collecting credentials.
