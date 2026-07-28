"""Shared container-invocation glue used by both the judge-live runner
(`runner.py`, one source vs. stored expected output) and the judge-gen
differential runner (`gen_runner.py`, two sources compared to each other).

All untrusted execution still goes through `app.sandbox.build_run_command`
unchanged — this module only holds the plumbing around it (subprocess
invocation, envelope parsing, image/filename resolution), never the
security contract itself.
"""

import base64
import json
import secrets
import subprocess
import uuid
from dataclasses import dataclass
from typing import Any

from app.config import get_settings
from app.contracts import Language
from app.sandbox import SandboxSpec, build_run_command

# Per-language source filename + image resolver.
SOURCE_FILENAME = {Language.PYTHON: "main.py", Language.JAVA: "Main.java", Language.CPP: "main.cpp"}


def image_for(language: Language) -> str:
    settings = get_settings()
    return {
        Language.PYTHON: settings.image_python,
        Language.JAVA: settings.image_java,
        Language.CPP: settings.image_cpp,
    }[language]


@dataclass
class ContainerOutcome:
    killed_by_worker: bool  # worker wall-timeout fired
    docker_returncode: int
    envelope: dict[str, Any] | None  # decoded run envelope (dynamic JSON)
    compile_log: str


def run_container(spec: SandboxSpec, *, stdin: bytes, wall_seconds: float) -> ContainerOutcome:
    cmd = build_run_command(spec)
    try:
        proc = subprocess.run(
            cmd, input=stdin, capture_output=True, timeout=wall_seconds
        )
    except subprocess.TimeoutExpired:
        # The docker CLI was killed, but the container keeps running — kill it.
        subprocess.run(["docker", "kill", spec.name], capture_output=True, check=False)
        return ContainerOutcome(True, -1, None, "")

    stdout = proc.stdout.decode(errors="replace")
    envelope: dict[str, Any] | None = None
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                envelope = json.loads(line)
            except json.JSONDecodeError:
                envelope = None
            break
    return ContainerOutcome(False, proc.returncode, envelope, stdout)


def decode_output(envelope: dict[str, Any]) -> bytes:
    return base64.b64decode(str(envelope.get("output_b64", "")))


def container_name(id_: uuid.UUID, stage: str) -> str:
    return f"dsa-judge-{id_.hex[:12]}-{stage}-{secrets.token_hex(3)}"
