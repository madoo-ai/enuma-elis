# Browser run, 2026-11-18

Model `litellm/prometheus`, agent `python-experiment`, modules
`fs,mutate,browser`. The server ran the rebuilt fork inside
`manus-dei/base:latest`; no `OPENCODE_EAGER_BROWSER` was set.

## Prompt

> Use only the python tool. In one Python program: `page = browser.page()`;
> `page.goto("data:text/html,<title>Probe</title><button id=go>Go</button>")`;
> `page.snapshot()`; `title = page.get("title")`; `attr = page.get("attr",
> "#go", name="id")`; `visible = page.is_("visible", "#go")`; `shot =
> page.screenshot("/tmp/browser-check.png")`; return those values and
> `len(shot.bytes)`. Do not use raw open, subprocess, or sockets.

## Result

One Python call, six `browser.call` child calls, no errors.

```json
{
  "title": "Probe",
  "attr": "go",
  "visible": true,
  "shot_path": "/tmp/browser-check.png",
  "shot_bytes": 4472
}
```

- Duration: 9.7 s.
- Tokens: 1,683 input, 340 output, 216 reasoning.
- Audit: `{rawOpen: 0, rawExec: 0, rawNet: 0}`.
- `filesChanged`: none (the screenshot lives in the container `/tmp`; the
  host returned its bytes to the program).
- Screenshot: [`screenshot.png`](screenshot.png), 4.4 KB.

## What this shows

- The Python `Page` reaches the native browser tool and the session Chromium.
  The first `browser.call` took 720 ms including browser readiness; later calls
  were 155-190 ms.
- `get` returns the decoded value, not the tool's JSON envelope: `"Probe"` and
  `"go"` in the result. `is_` returns a bool.
- The host read the saved screenshot and attached base64 bytes. `shot.bytes`
  decoded to 4,472 bytes, matching the copied PNG.
- The program stayed inside the typed surface: no raw file, process, or socket
  calls. The model did not need `subprocess` to drive the browser.

## Earlier probe

A first run with the same server shape but `get` returning raw JSON produced the
same page and screenshot, but the model had to `json.loads` the title and had to
retry once after forgetting the `from agent import browser` import. That is why
`Page.get` now decodes the value. The clean run above is after that change.
