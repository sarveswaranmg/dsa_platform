# Build context = services/judge/runners/
#   docker build -f runners/java/Dockerfile -t dsa-judge-java:21 runners
# Pinned to the Noble LTS base (stable python3.12); the rolling :21-jdk tag
# pulls an unstable python from a dev-release Ubuntu.
FROM eclipse-temurin:21-jdk-noble

ENV HOME=/work DEBIAN_FRONTEND=noninteractive

# python3 runs the shared entrypoint; JDK 21 (javac + java) is already present.
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/*

COPY entrypoint.py /entrypoint.py

USER 1000:1000
ENTRYPOINT ["python3", "/entrypoint.py"]
