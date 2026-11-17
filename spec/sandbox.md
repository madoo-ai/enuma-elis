# Sandbox policy

The host runs the program under `bwrap`. The container is already the security
boundary; this sandbox is the experiment's behavioral boundary and the
"no system writes" policy.

## Mounts

```bash
bwrap \
  --die-with-parent \
  --new-session \
  --ro-bind / / \
  --dev /dev \
  --proc /proc \
  --tmpfs /tmp \
  --bind /home/ubuntu/workspace /home/ubuntu/workspace \
  --ro-bind "$RUN_DIR" /run/agent \
  --chdir /home/ubuntu/workspace \
  --clearenv \
  --setenv PATH "$PATH" \
  --setenv HOME /tmp/home \
  --setenv TMPDIR /tmp \
  --setenv LANG C.UTF-8 \
  --setenv LC_ALL C.UTF-8 \
  --setenv PYTHONUNBUFFERED 1 \
  --setenv PYTHONDONTWRITEBYTECODE 1 \
  --setenv PYTHONPATH /opt/manus/python/current/lib \
  --setenv AGENT_BRIDGE_FD 3 \
  --setenv AGENT_RESULT_FD 4 \
  --preserve-fds 2 \
  -- /opt/manus/python/current/bin/python3 /run/agent/zz_main.py
```

- `/` is read-only. `/etc`, `/usr`, `~/.config`, and `~/.local` cannot be
  written. `sudo` cannot remount; `bwrap` drops the capability.
- `/home/ubuntu/workspace` is read-write in the experiment arms. A strict arm
  replaces it with `--ro-bind`.
- `/tmp` is a private tmpfs. The container's shared `/tmp` is not exposed.
- `$RUN_DIR` lives outside `/tmp` (for example
  `/home/ubuntu/.local/state/manus/python/<callID>`), because a tmpfs over
  `/tmp` would shadow the bind source.
- `--preserve-fds 2` keeps fd 3 and fd 4.

## Environment

Only this list reaches the child:

| Variable | Value |
| --- | --- |
| `PATH` | host PATH, so toolchains still run |
| `HOME` | `/tmp/home` |
| `TMPDIR` | `/tmp` |
| `LANG`, `LC_ALL` | `C.UTF-8` |
| `PYTHONUNBUFFERED`, `PYTHONDONTWRITEBYTECODE` | `1` |
| `PYTHONPATH` | `/opt/manus/python/current/lib` |
| `AGENT_BRIDGE_FD`, `AGENT_RESULT_FD` | `3`, `4` |
| `GOPATH`, `GOTOOLCHAIN` | host values |
| `GOCACHE`, `GOMODCACHE` | `/tmp/gocache`, `/tmp/gomodcache` (or rw cache binds) |
| `CARGO_HOME`, `RUSTUP_HOME`, `NVM_DIR` | host values, when present |

Never pass: `OPENCODE_API_KEY`, `LITELLM_BASE_URL`, `GH_TOKEN`, `GITHUB_TOKEN`,
`MANUS_GIT_TOKEN`, `GIT_ASKPASS`, `SSH_AUTH_SOCK`, cloud credentials.

`HOME=/tmp/home` means Go's default cache is cold. Set `GOCACHE` and
`GOMODCACHE` to `/tmp` paths, or bind the real caches read-write if warm builds
matter more than the strict two-path rule.

## Runtime

The runtime is a read-only volume at `/opt/manus/python`:

```text
/opt/manus/python/
  releases/<version>/
    bin/python3
    lib/python3.13/...
    lib/agent/...          # SDK package; PYTHONPATH points at lib/
    lib/sitecustomize.py   # audit hook
    manifest.json
  current -> releases/<version>
```

The stable image symlink is `/usr/local/bin/python3 -> /opt/manus/python/current/bin/python3`.
If the volume is absent, the symlink is broken and the shell falls back to the
distro Python; the `python` tool returns `Unavailable` rather than running
without the SDK.

## Audit hook

`sitecustomize.py` is installed at `lib/sitecustomize.py` and loads automatically.
It installs an audit hook that reports raw `open` writes, `subprocess`/`os.system`,
and `socket.connect` to fd 3. It is measurement, not enforcement; the mounts are
the enforcement. `ctypes` can bypass the hook; the snapshot diff is the backstop.
