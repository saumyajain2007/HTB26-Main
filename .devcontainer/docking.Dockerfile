# amd64 image for the Vina docking worker (Vina publishes Linux x86_64 wheels only).
# Build: docker build --platform linux/amd64 -f .devcontainer/docking.Dockerfile -t htb-docking:local .
FROM python:3.11-slim-bookworm
COPY .devcontainer/docking-requirements.txt /tmp/docking-requirements.txt
RUN pip install --no-cache-dir -r /tmp/docking-requirements.txt && pip install --no-cache-dir uv
