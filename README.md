# Orbit — a human-in-the-loop career agent

Orbit is a local workspace for turning a job description into a focused, ATS-friendly resume and a reviewable application handoff. It includes a polished dashboard and an optional Chrome/Chromium Manifest V3 connector for the user's already-open Indeed and Arena.ai tabs.

## Run the dashboard

```bash
npm install
npm run dev
```

Then open the Vite URL. The dashboard is usable in demo mode without any external accounts: open the job queue, inspect a role, tailor its resume, review the checks, and print/save a PDF from the browser print dialog.

## Optional browser connector

The connector lives in [`extension/`](./extension). Load that folder as an unpacked extension from `chrome://extensions` while Developer mode is enabled. With an individual Indeed job page and an existing Arena.ai session open, **Sync Indeed jobs** reads the visible job description into Orbit. **Send the brief to your open Arena.ai session** focuses the Arena composer and inserts a prompt containing the supplied resume facts and full job description.

The connector does not request or store passwords, does not press Send in Arena, and does not submit applications. Orbit's Safe mode intentionally keeps upload and Submit as explicit user actions so each application can be checked before sending. After changing extension files, click **Reload** for Orbit in `chrome://extensions`; the handoff dialog also provides a copy-and-paste fallback if Arena's composer is still loading.

## Build

```bash
npm run build
```
