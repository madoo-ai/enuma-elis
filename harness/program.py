from agent import fs, mutate


def Run(ctx, a):
    page = fs.read("README.md")
    files = fs.glob("*.txt")
    edited = mutate.edit("sample.txt", "TODO:", "DONE:")
    written = mutate.write("out.txt", "written by mutate\n")

    raw_ok = False
    try:
        with open("raw.txt", "w") as handle:
            handle.write("raw\n")
        raw_ok = True
    except OSError:
        pass

    system_blocked = False
    try:
        with open("/etc/enuma-harness", "w") as handle:
            handle.write("no\n")
    except OSError:
        system_blocked = True

    return {
        "text": page.text,
        "globbed": [entry.path for entry in files.entries],
        "edited": edited.file,
        "written": written.bytes,
        "raw_ok": raw_ok,
        "system_blocked": system_blocked,
    }
