# TrustLens for Chrome

Right-click to check what you see on any website, with TrustLens running on your computer.

| Right-click on | Menu item | What happens |
|---|---|---|
| An image | Check this image with TrustLens | Full image analysis: face-swap detector, AI review, forensic tests, signed report |
| A video | Check this video with TrustLens | Frames, faces and the face-swap detector on each, soundtrack |
| Selected text | Fact-check "…" with TrustLens | Claims, news coverage, published fact-checks, warning signs in the wording; campus claims are also compared with your VTOP records |
| Empty space on a page | Fact-check this page with TrustLens | The same, for the article's text |

**On WhatsApp Web and other sites that replace Chrome's right-click menu:** select text and a yellow **Fact-check** button appears next to it (or press **Alt+Shift+F**); hover a photo or video in WhatsApp Web or Telegram Web and click **Check with TrustLens**.

The popup shows whether TrustLens is running and has a box for pasting a forwarded message.

## Install (developer mode, 1 minute)

1. Start TrustLens: `python server.py`.
2. Open `chrome://extensions` and switch on **Developer mode** (top right).
3. Click **Load unpacked** and choose this `extension` folder.
4. Pin it: click the puzzle icon in the toolbar, then the pin next to TrustLens.

Works in Chrome, Edge and Brave. Images on WhatsApp Web and Telegram live inside the page (blob: links); the extension reads them from the page, up to 6 MB. Larger files: download them and open them in TrustLens.

**Privacy:** the extension only talks to TrustLens on this computer (`http://127.0.0.1:8000`, changeable in the popup). Files go nowhere else, except to the AI review you configured in TrustLens.
