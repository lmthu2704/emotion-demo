# Emotion demo

Webcam and microphone body-language demo that runs entirely in your browser.

**Try it:** https://lmthu2704.github.io/emotion-demo/

- **Face**: expression recognition with [face-api.js](https://github.com/vladmandic/face-api) (7 classes)
- **Hands**: gestures and waving with [MediaPipe Gesture Recognizer](https://ai.google.dev/edge/mediapipe/solutions/vision/gesture_recognizer)
- **Voice**: speech emotion with [Speech-Emotion-Classification-ONNX](https://huggingface.co/onnx-community/Speech-Emotion-Classification-ONNX) via transformers.js (click "Start voice"; ~95 MB download the first time)

On the hosted page, video and audio are processed locally and never uploaded. The detectors are rough estimates, not reliable readings of how someone feels.

## Run locally with the voice bot and AI explanations

Two panels use your OpenAI key, so they only appear when you run the local server:

- **Talk to the bot**: a voice conversation through OpenAI's Realtime API (`gpt-realtime-2.1-mini`). After each thing you say, the page sends the bot a one-line summary of the face and voice readings (for example `face sad 62%, neutral 25%; voice calm 48%`), and the bot adjusts its tone. Your voice and that summary go to OpenAI; the video stays in the browser. The panel shows a running cost estimate. A 5-minute chat costs roughly $0.10, or about $0.30 with `OPENAI_REALTIME_MODEL=gpt-realtime-2.1` in `.env`.
- **Explain**: sends one snapshot plus the readings to OpenAI (`gpt-4.1`), which describes what the person is doing. Each explanation is a paid call (about $0.003).

1. Copy `.env.example` to `.env` and add your `OPENAI_API_KEY`.
2. `python server.py`
3. Open http://localhost:8765

The bot's instructions are `BOT_INSTRUCTIONS` in `server.py`.

## Put it online with a passcode (link works any time)

To give people a link that works whenever they open it, even when your computer is off, host the server on [Render](https://render.com)'s free plan:

1. Push this repo to GitHub; `render.yaml` holds the settings.
2. Sign up at render.com with your GitHub account, then choose **New → Blueprint** and pick this repo.
3. Render asks for two values. Paste your OpenAI key into `OPENAI_API_KEY`, and a passcode of a few words into `DEMO_PASSCODE`. They stay in Render's settings, never in the repo.
4. Once it's deployed, send people the `https://….onrender.com` address and the passcode. Their browser opens a sign-in box: the passcode goes in the **password** field, and the user name can be anything or left empty.

The free plan sleeps after 15 minutes without visitors, so the first visit after a break takes about a minute to load. Anyone with the passcode can spend money on your OpenAI account at any time, so set a monthly budget on your OpenAI account. To cut off access, change `DEMO_PASSCODE` in Render's **Environment** settings or delete the service. The server refuses to start online without a passcode.

## Share it from your computer with a passcode (quick, temporary)

To let other people try the bot and Explain from their own computers while yours is running:

1. Add a passcode to `.env`, for example `DEMO_PASSCODE=purple-otter-sings`. Use a few words, not a short PIN. After 10 wrong passcodes in 10 minutes the server refuses everyone for a while, which makes guessing a few-word passcode impractical. `.env` is in `.gitignore`, so the passcode never goes to GitHub.
2. Restart `python server.py`. The startup line should say `passcode on`.
3. In a second terminal, start a Cloudflare quick tunnel (no account needed):
   ```
   winget install --id Cloudflare.cloudflared
   cloudflared tunnel --url http://localhost:8765
   ```
4. Send people the `https://….trycloudflare.com` address it prints, plus the passcode. Before showing anything, their browser opens a sign-in box: the passcode goes in the **password** field, and the user name can be anything or left empty.

With the passcode set, you get the sign-in box on http://localhost:8765 too. Remove the line from `.env` and restart to go back to using it without one.

Everyone with the passcode spends money on your OpenAI account, so share it only with people you trust. When the demo is over, stop the tunnel with Ctrl+C and the address stops working. Each run gives a new address. As on localhost, visitors' video stays in their browser; their voice and the detector readings go to OpenAI.

The GitHub Pages link above can't be locked or run the bot: it only serves the page's files, so it always shows the free, in-browser part.

Never start a tunnel without `DEMO_PASSCODE`. The server's localhost-only check stops other websites, but not someone calling the tunnel address directly with a script.
