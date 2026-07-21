# Build context = services/judge/runners/  (so entrypoint.py is shared).
#   docker build -f runners/python/Dockerfile -t dsa-judge-python:3.12 runners
FROM python:3.12-slim

# HOME points at the writable tmpfs; the container runs as numeric uid 1000
# (no named user needed — --user 1000:1000 is forced by the sandbox too).
ENV HOME=/work

COPY entrypoint.py /entrypoint.py

USER 1000:1000
ENTRYPOINT ["python3", "/entrypoint.py"]
