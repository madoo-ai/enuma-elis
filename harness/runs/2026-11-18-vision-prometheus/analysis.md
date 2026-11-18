# Vision run, 2026-11-18

Upstream issue: https://github.com/madoo-ai/manus-dei/issues/153

Model `litellm/prometheus` (`openai/deepseek-v4.1-flash`), agent
`python-experiment`, modules `fs,mutate,browser`. The server ran the fork in
`manus-dei/base:latest` with the normal bwrap sandbox.

## Config fix

The earlier harness config declared only a name and token limit for
`prometheus`. Its LiteLLM model metadata says `supports_vision: true`, but
opencode saw:

```json
{"attachment": false, "input": {"image": false}}
```

That capability gate, not the model, caused the earlier “does not support image
input” answer. The harness now declares:

```json
{
  "attachment": true,
  "reasoning": true,
  "tool_call": true,
  "modalities": {"input": ["text", "image"], "output": ["text"]}
}
```

## Prompt

The page was a canvas, not DOM text:

```text
data:text/html,<canvas id="c" width="600" height="300"></canvas>
<script>
  const x = c.getContext("2d")
  x.fillStyle = "#123456"; x.fillRect(0, 0, 600, 300)
  x.fillStyle = "#ffffff"; x.font = "64px sans-serif"
  x.fillText("VISION-OK-739", 30, 160)
</script>
```

The model was told to open it, take a screenshot, return the `Screenshot`, and
not use `snapshot`, `read`, `get`, or `evaluate`. The first Python program
failed because the model forgot `from agent import browser`; the retry
succeeded.

## Result

- Python calls: 2 (one import error, one success).
- Child `browser.call` calls: 3.
- Screenshot attachment: `image/png`, 20,118 characters of data URL text.
- Text output: only `{"path": "/tmp/vision.png", "mime": "image/png"}`.
- Model answer:

> Text: `VISION-OK-739` — large white sans-serif characters
> Background: `#123456` (RGB 18, 52, 86); text is white.

- Screenshot: [`screenshot.png`](screenshot.png), 15 KB.

## What this shows

- The Python tool result carried the PNG as a `file` attachment.
- The session converted it to a model media part; the model saw the image.
- The model read the exact canvas text and colors, so this was not a DOM read.
- The previous text-only claim was a harness capability-config bug. LiteLLM and
  the provider both support vision for this model.
