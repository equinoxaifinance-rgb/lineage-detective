FROM docker:29.6.2-dind-rootless@sha256:9ca5d2d7f364f7c48579ba57dcb218b37387f214943f6446f62a200935511278 AS docker-rootless

FROM python:3.11-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    XDG_RUNTIME_DIR=/home/lineage/.docker/run \
    DOCKER_HOST=unix:///home/lineage/.docker/run/docker.sock \
    DOCKER_API_VERSION=1.54 \
    PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates fuse-overlayfs iproute2 passwd procps uidmap \
    && find /var/lib/apt/lists -mindepth 1 -delete

# Debian's distro Docker package currently carries an old Go/runc toolchain.
# Import the current official, digest-pinned rootless Docker binaries instead.
# This keeps the real DataHub-in-DataHub runtime while avoiding that stale
# dependency chain.
COPY --from=docker-rootless /usr/local/bin/containerd /usr/local/bin/containerd
COPY --from=docker-rootless /usr/local/bin/containerd-shim-runc-v2 /usr/local/bin/containerd-shim-runc-v2
COPY --from=docker-rootless /usr/local/bin/ctr /usr/local/bin/ctr
COPY --from=docker-rootless /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker-rootless /usr/local/bin/docker-init /usr/local/bin/docker-init
COPY --from=docker-rootless /usr/local/bin/docker-proxy /usr/local/bin/docker-proxy
COPY --from=docker-rootless /usr/local/bin/dockerd /usr/local/bin/dockerd
COPY --from=docker-rootless /usr/local/bin/rootlesskit /usr/local/bin/rootlesskit
COPY --from=docker-rootless /usr/local/bin/runc /usr/local/bin/runc

WORKDIR /app

COPY requirements-runtime.lock /app/requirements-runtime.lock
COPY requirements-datahub-sidecar-linux.lock /app/requirements-datahub-sidecar-linux.lock

RUN python -m pip install --no-cache-dir --require-hashes -r /app/requirements-runtime.lock \
    && python -m venv /opt/datahub-sidecar \
    && /opt/datahub-sidecar/bin/python -m pip install --no-cache-dir --require-hashes \
       -r /app/requirements-datahub-sidecar-linux.lock \
    && python -m pip check \
    && /opt/datahub-sidecar/bin/python -m pip check

RUN /usr/sbin/groupadd --system --gid 1000 lineage \
    && /usr/sbin/useradd --uid 1000 --gid 1000 --create-home --home-dir /home/lineage lineage \
    && mkdir -p /home/lineage/.docker/run /home/lineage/.local/share/docker /app/state \
    && chown -R lineage:lineage /home/lineage /app \
    && printf 'lineage:100000:65536\n' >> /etc/subuid \
    && printf 'lineage:100000:65536\n' >> /etc/subgid

COPY --chown=lineage:lineage . /app

RUN python -c "from pathlib import Path; files=(Path('/app/cloudflare-fullstack/entrypoint.sh'),Path('/app/cloudflare-fullstack/start.sh')); bad=[str(path) for path in files if b'\r' in path.read_bytes()]; assert not bad, f'carriage returns in shell scripts: {bad}'" \
    && chmod 0755 /app/cloudflare-fullstack/entrypoint.sh /app/cloudflare-fullstack/start.sh \
    && python -m compileall -q app.py src tools cloudflare-fullstack \
    && python -m unittest discover -s tests -q \
    && python tools/verify_security_boundary.py \
    && python tools/verify_release_examples.py

# The entrypoint needs root only long enough to create Cloudflare's missing /dev/shm.
# It permanently drops to uid/gid lineage before Docker, DataHub, or Streamlit starts.
USER root

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=12m --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3)"

ENTRYPOINT ["/app/cloudflare-fullstack/entrypoint.sh"]
