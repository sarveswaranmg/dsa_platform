#!/usr/bin/env python3
"""In-container entrypoint, shared by all three runner images.

Runs inside the locked-down sandbox as the non-root user. Two subcommands:

  entrypoint.py compile <lang>          — build the artifact in /art; exit code
                                          is the compiler's (non-zero => CE).
                                          Compiler log goes to stdout.
  entrypoint.py run <lang> <wall_ms>    — execute the built program reading
                                          stdin, and print ONE JSON envelope to
                                          stdout describing the outcome.

Stdlib only; the program's own stdout is captured to /work and returned inside
the envelope (base64), so it can't be confused with the envelope itself.
"""

import base64
import json
import os
import resource
import subprocess
import sys
import time

ART = "/art"
WORK = "/work"
MAX_OUTPUT_BYTES = int(os.environ.get("MAX_OUTPUT_BYTES", "1000000"))

COMPILE = {
    "cpp": ["g++", "-O2", "-std=c++20", "-o", f"{ART}/main", f"{ART}/main.cpp"],
    "java": ["javac", "-d", ART, f"{ART}/Main.java"],
    "python": ["python3", "-m", "py_compile", f"{ART}/main.py"],
}
RUN = {
    "cpp": [f"{ART}/main"],
    "java": ["java", "-XX:-UsePerfData", "-cp", ART, "Main"],
    "python": ["python3", f"{ART}/main.py"],
}


def _cgroup_oom_killed() -> bool:
    # cgroup v2: authoritative signal that the kernel OOM-killed something in
    # this container's cgroup.
    try:
        with open("/sys/fs/cgroup/memory.events") as fh:
            for line in fh:
                if line.startswith("oom_kill "):
                    return int(line.split()[1]) > 0
    except OSError:
        pass
    return False


def do_compile(lang: str) -> int:
    proc = subprocess.run(COMPILE[lang], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    sys.stdout.buffer.write(proc.stdout)
    sys.stdout.buffer.flush()
    return proc.returncode


def do_run(lang: str, wall_ms: int) -> int:
    wall_s = wall_ms / 1000.0
    out_path = f"{WORK}/output"
    timed_out = False
    start = time.monotonic()
    with open(out_path, "wb") as out:
        try:
            proc = subprocess.run(
                RUN[lang],
                stdin=sys.stdin.buffer,
                stdout=out,
                stderr=subprocess.DEVNULL,
                timeout=wall_s,
            )
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            exit_code = 124
    elapsed_ms = int((time.monotonic() - start) * 1000)

    # Child-only peak RSS (excludes this entrypoint), kB on Linux.
    memory_kb = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss

    with open(out_path, "rb") as fh:
        data = fh.read(MAX_OUTPUT_BYTES + 1)
    truncated = len(data) > MAX_OUTPUT_BYTES
    data = data[:MAX_OUTPUT_BYTES]

    envelope = {
        "exit_code": exit_code,
        "timed_out": timed_out,
        "oom_killed": _cgroup_oom_killed(),
        "time_ms": elapsed_ms,
        "memory_kb": int(memory_kb),
        "truncated": truncated,
        "output_b64": base64.b64encode(data).decode(),
    }
    print(json.dumps(envelope))
    return 0


def main() -> int:
    mode = sys.argv[1]
    lang = sys.argv[2]
    if mode == "compile":
        return do_compile(lang)
    if mode == "run":
        return do_run(lang, int(sys.argv[3]))
    raise SystemExit(f"unknown mode: {mode}")


if __name__ == "__main__":
    sys.exit(main())
