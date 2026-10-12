# Emotion demo

Webcam and microphone body-language demo that runs entirely in your browser.

**Try it:** https://lmthu2704.github.io/emotion-demo/

- **Face**: expression recognition with [face-api.js](https://github.com/vladmandic/face-api) (7 classes)
- **Hands**: gestures and waving with [MediaPipe Gesture Recognizer](https://ai.google.dev/edge/mediapipe/solutions/vision/gesture_recognizer)
- **Voice**: speech emotion with [Speech-Emotion-Classification-ONNX](https://huggingface.co/onnx-community/Speech-Emotion-Classification-ONNX) via transformers.js (click "Start voice"; ~95 MB download the first time)

Video and audio are processed locally and never uploaded. The detectors are rough estimates, not reliable readings of how someone feels.

## Run locally with AI explanations

The "Explain" panel sends a snapshot to OpenAI and only works when you run the local server:

1. Copy `.env.example` to `.env` and add your `OPENAI_API_KEY`.
2. `python server.py`
3. Open http://localhost:8765

Each explanation is a paid OpenAI API call.
