FROM python:3.11-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93 AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

WORKDIR /app

COPY requirements-runtime.lock /app/requirements-runtime.lock
RUN python -m pip install --no-cache-dir --require-hashes -r requirements-runtime.lock

RUN groupadd --system lineage \
    && useradd --system --gid lineage --create-home --home-dir /home/lineage lineage \
    && mkdir -p /home/lineage/.streamlit \
    && chown -R lineage:lineage /home/lineage /app

USER lineage


FROM base AS verified

COPY --chown=lineage:lineage . /app

RUN python -m pip check \
    && python -m compileall -q app.py src tests quickstart.py tools \
    && python -m unittest discover -s tests -q \
    && python tools/verify_security_boundary.py \
    && python tools/verify_release_examples.py


FROM base AS runtime

COPY --from=verified --chown=lineage:lineage /app/app.py /app/app.py
COPY --from=verified --chown=lineage:lineage /app/.streamlit /app/.streamlit
COPY --from=verified --chown=lineage:lineage /app/src /app/src
COPY --from=verified --chown=lineage:lineage /app/assets /app/assets
COPY --from=verified --chown=lineage:lineage /app/repair_sandbox /app/repair_sandbox

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3)"

CMD ["python", "-m", "streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
