# Native read/fetch attachments, 2026-11-18

Model `litellm/prometheus` (`openai/deepseek-v4.1-flash`), agent
`python-experiment`, modules `fs,web`. Normal bwrap sandbox.

## Prompt

> Use only the python tool. In one Python program:
> `a = fs.read("vision.png")`; `b = web.fetch("http://127.0.0.1:8000/vision.png")`;
> return both. After the tool result, tell me the exact text visible in the
> images.

`vision.png` is the canvas screenshot from the vision run: white
`VISION-OK-739` on `#123456`. The file was in the workspace and served over a
local HTTP server inside the container.

## Result

One Python call, two child calls: `fs.read` and `web.fetch`.

The Python tool result had two `image/png` attachments, each 20,118 characters
of data URL. The text output was metadata only:

```json
{
  "read": {
    "path": "vision.png",
    "mime": "image/png"
  },
  "fetch": {
    "path": "http://127.0.0.1:8000/vision.png",
    "url": "http://127.0.0.1:8000/vision.png",
    "mime": "image/png",
    "text": "Image fetched successfully",
    "title": "http://127.0.0.1:8000/vision.png (image/png)"
  }
}
```

The model read the image:

> Both images show the same text: `VISION-OK-739`.

- Duration: 16.0 s.
- Tokens: 1,727 input, 306 output, 156 reasoning.
- Audit: `{rawOpen: 0, rawExec: 0, rawNet: 0}`.
- `filesChanged`: none.
- Image: [`vision.png`](vision.png).

## What this shows

- `read` on an image now returns `Image` in Python, and the Python tool
  reconstructs the native `file` attachment.
- `webfetch` on an image now returns `FetchResult(kind="attachment", mime,
  data)`, with the same model-facing attachment behavior.
- The base64 payload is stripped from the model-visible text in both cases.
- The model saw the pixels, not a status string or a base64 dump.
