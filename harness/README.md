# Sandbox harness

Runs the Python SDK inside the same image manus-dei uses, under the same
`bwrap` shape the fork adapter uses.

```bash
./harness/run.sh
```

Requirements: Docker, and `manus-dei/base:latest` (or set
`MANUS_BASE_IMAGE`). The script installs `bubblewrap` inside the throwaway
container; the production base image should carry it.

## What it checks

- The SDK handshake, call stream, and final envelope over stdio.
- `fs.read`, `fs.glob`, `mutate.edit`, `mutate.write` against a real workspace.
- A raw `open("raw.txt", "w")` inside the sandbox succeeds and is audited.
- A raw `open("/etc/enuma-harness", "w")` fails because `/` is read-only.
- The audit hook reports both raw opens.
- The run directory is readable at `/tmp/agent` after the private `/tmp`
  tmpfs is mounted.

Expected output ends with `HARNESS OK`.

## Two findings from the first run

1. **Default Docker seccomp blocks bwrap.** The first run died with
   `No permissions to create a new namespace`. `--security-opt
   seccomp=unconfined` fixes it; `--cap-add SYS_ADMIN` alone does not (the
   default profile still blocks `pivot_root`). A real session needs the
   unconfined profile, a custom profile that allows the namespace syscalls, or
   a different sandbox (Landlock, read-only rootfs). deusd's `HostConfig`
   currently sets no security options.
2. **`/run/agent` cannot be created on a read-only root.** bwrap failed with
   `Can't mkdir /run/agent: Read-only file system`. The adapter now binds the
   run directory at `/tmp/agent` after `--tmpfs /tmp`. The source stays outside
   `/tmp`; only the destination is inside the private tmpfs.

The harness uses the distro `python3` as the runtime. Production uses the
relocatable volume at `/opt/manus/python/current`.
