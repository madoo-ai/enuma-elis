# Unbounded run, 2026-11-18

Model `litellm/prometheus`, agent `python-experiment`, modules
`fs,mutate,shell,browser`. The server ran the rebuilt fork inside
`manus-dei/base:latest` with `OPENCODE_PYTHON_SANDBOX=none` and
`OPENCODE_PYTHON_BLOCK_RAW_EXEC=0`.

## Prompt

> Use only the python tool. This is an unbounded test: raw open and subprocess
> are allowed. In one Python program: read `/etc/hostname` with `open()`; run
> `["id", "-u"]` with `subprocess.run(capture_output=True, text=True)`; open a
> `data:` URL with `browser.page()`; take a screenshot to
> `/tmp/attach-check.png`; return the hostname, uid, and the `Screenshot`
> object.

## Result

One Python call, three `browser.call` child calls, no errors.

```json
{
  "hostname": "a017145762dc",
  "uid": "1000",
  "shot": {
    "path": "/tmp/attach-check.png",
    "mime": "image/png"
  }
}
```

- Duration: 7.6 s.
- Audit: `{rawOpen: 0, rawExec: 1, rawNet: 0}`. The audit hook records raw
  writes, not reads, so the `/etc/hostname` read does not appear.
- Screenshot: [`screenshot.png`](screenshot.png), 6.6 KB.
- The Python tool result carries the image as a `file` attachment with a
  `data:image/png;base64,...` URL. The text output has only the path and MIME.
- The model reported that it could not visually inspect the image. At that
  point the harness config omitted `attachment` and image modalities, so
  opencode hid the media. That was a config bug, not a model limit; the later
  [vision run](../2026-11-18-vision-prometheus/analysis.md) reads a canvas
  screenshot correctly after the config fix.

## What this shows

- Without bwrap the runtime executes directly in the container. Raw `open` and
  `subprocess` both work: the program read the host hostname and ran `id`.
- The host and Python now share `/tmp`. The screenshot path is directly usable;
  the adapter does not copy bytes into the Python program.
- Returning the `Screenshot` object still becomes a model attachment at the
  Python tool boundary. The base64 is internal to the tool result, not part of
  the model text.
- The attachment path is independent of the sandbox mode. With the corrected
  model capabilities, the model consumes the image as a media part.
