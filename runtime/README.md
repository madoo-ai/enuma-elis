# Runtime

The runtime is a relocatable CPython plus the `agent` SDK, delivered from a
read-only volume. It is built and released by this repository; the fork only
consumes it.

## Target layout

```text
/opt/manus/python/
  releases/<version>/
    bin/python3
    lib/python3.13/...
    lib/agent/...
    lib/sitecustomize.py
    manifest.json
  current -> releases/<version>
```

`PYTHONPATH` points at `lib/`, so `import agent` resolves `lib/agent/` and
`sitecustomize.py` loads as a top-level module.

## Build sketch

1. Fetch a relocatable CPython build for the target platform (`linux/amd64`,
   glibc-compatible with Ubuntu 26.04).
2. Copy the `agent/` package into `lib/agent/`.
3. Copy `sitecustomize.py` to `lib/sitecustomize.py`.
4. Write `manifest.json` with the runtime version, protocol version, Python
   version, and tool-manifest hash.
5. Publish the tree as `releases/<version>`; update `current` atomically.
6. Install `bubblewrap` in the base image and create the mount point.

## Manifest

```json
{
  "version": "2026.11.1",
  "protocol": 1,
  "python": "3.13.5",
  "toolManifestHash": "sha256:...",
  "sha256": "..."
}
```

The fork resolves `current`, reads this file, and refuses to run if the protocol
or tool-manifest hash does not match the binary it is paired with.

## Delivery

The runtime is the `runtime-only` release lane: write a new release directory,
verify the hash, and swap `current`. Running programs keep their open files;
the next program gets the new release. The volume is mounted read-only in
sessions and written only by a trusted helper.
