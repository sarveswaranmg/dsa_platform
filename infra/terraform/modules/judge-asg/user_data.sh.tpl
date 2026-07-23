#!/bin/bash
# Dedicated judge node: this instance runs nothing but the judge worker
# container and the sandbox containers it launches via the Docker socket
# (DooD) — see docs/DECISIONS.md for why (host docker.sock access is
# effectively host root, so node-pool isolation matters).
set -euxo pipefail

dnf install -y docker
systemctl enable --now docker

%{ if judge_runtime == "gvisor" ~}
# gVisor install (see docs/DECISIONS.md) — registers the runsc runtime with
# the Docker daemon so `docker run --runtime=runsc` (services/judge/app/sandbox.py)
# resolves.
(
  set -e
  ARCH=$(uname -m)
  URL="https://storage.googleapis.com/gvisor/releases/release/latest/$ARCH"
  curl -fsSL "$URL/runsc" -o /usr/local/bin/runsc
  curl -fsSL "$URL/containerd-shim-runsc-v1" -o /usr/local/bin/containerd-shim-runsc-v1
  chmod +x /usr/local/bin/runsc /usr/local/bin/containerd-shim-runsc-v1
)
mkdir -p /etc/docker
python3 - <<'PYEOF'
import json, os
path = "/etc/docker/daemon.json"
config = json.load(open(path)) if os.path.exists(path) else {}
config.setdefault("runtimes", {})["runsc"] = {"path": "/usr/local/bin/runsc"}
json.dump(config, open(path, "w"))
PYEOF
systemctl restart docker
%{ endif ~}

aws ecr get-login-password --region ${aws_region} | docker login --username AWS --password-stdin ${ecr_registry}

mkdir -p /tmp/dsa-judge

docker run -d \
  --name judge \
  --restart always \
  --network host \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /tmp/dsa-judge:/tmp/dsa-judge \
%{ for key, value in environment ~}
  -e "${key}=${value}" \
%{ endfor ~}
  "${image}"
