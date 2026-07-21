# Build context = services/judge/runners/
#   docker build -f runners/cpp/Dockerfile -t dsa-judge-cpp:13 runners
FROM gcc:13

ENV HOME=/work DEBIAN_FRONTEND=noninteractive

# python3 runs the shared entrypoint; g++ 13 is already present.
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/*

COPY entrypoint.py /entrypoint.py

USER 1000:1000
ENTRYPOINT ["python3", "/entrypoint.py"]
