#!/bin/sh
set -eu

# Debian keeps dockerd and account-management helpers in /usr/sbin. The app
# interpreter stays on the fixed runtime; only system command discovery is
# widened here for the rootless Docker bootstrap.
export PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

STATUS_FILE="${LINEAGE_BOOT_STATUS:-/app/state/bootstrap.json}"
MYSQL_IMAGE="${MYSQL_IMAGE:-mysql@sha256:212fe73edca5df6ff14826d5eb975c914bfb91f82a2e923f9050568f99525da1}"
OPENSEARCH_IMAGE="${OPENSEARCH_IMAGE:-opensearchproject/opensearch@sha256:e96cc6ae1500a073d973c0906f30f7cf4d9c461f32f855f9242a2da933660cdd}"
KAFKA_IMAGE="${KAFKA_IMAGE:-confluentinc/cp-kafka@sha256:9cdc8119cb39c45f0efa6da8e2220058020c7433e3ba3a3ce11a8006a18cb336}"
DATAHUB_UPGRADE_IMAGE="${DATAHUB_UPGRADE_IMAGE:-acryldata/datahub-upgrade:v1.6.0@sha256:6e6b9f09165007004c20e9387e6ca1a171d1425fd76ae807b217c5dc7883ff02}"
DATAHUB_GMS_IMAGE="${DATAHUB_GMS_IMAGE:-acryldata/datahub-gms:v1.6.0@sha256:672bceed7f36f751ab3302c30826c6ba124d1c0fd8d24c3724e725078b864018}"
BRIDGE_IMAGE="${BRIDGE_IMAGE:-python:3.11-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93}"
export DATAHUB_SERVER="${DATAHUB_SERVER:-http://127.0.0.1:8080}"
export DATAHUB_GMS_URL="${DATAHUB_GMS_URL:-$DATAHUB_SERVER}"
export DATAHUB_GMS_TOKEN="${DATAHUB_GMS_TOKEN:-}"
export DATAHUB_MCP_EXECUTABLE="${DATAHUB_MCP_EXECUTABLE:-/opt/datahub-sidecar/bin/mcp-server-datahub}"
# Optional DataHub CLI analytics must never hold the real judge path hostage
# when the hosting platform restricts unrelated outbound telemetry.
export DATAHUB_TELEMETRY_ENABLED=false
export LINEAGE_RUN_MODE="${LINEAGE_RUN_MODE:-public_judge}"
export LINEAGE_BUNDLED_DATAHUB="${LINEAGE_BUNDLED_DATAHUB:-1}"

# Generate internal bootstrap credentials per cold start. They never leave the
# private container network and are not shipped in source or image history.
MYSQL_PASSWORD="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
MYSQL_ROOT_PASSWORD="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
TOKEN_SERVICE_SALT="$(python -c 'import secrets; print(secrets.token_hex(32))')"
TOKEN_SERVICE_SIGNING_KEY="$(python -c 'import secrets; print(secrets.token_hex(48))')"

status() {
  percent="$1"
  stage="$2"
  detail="$3"
  python - "$STATUS_FILE" "$percent" "$stage" "$detail" <<'PY'
import json, os, sys, tempfile
path, percent, stage, detail = sys.argv[1:]
os.makedirs(os.path.dirname(path), exist_ok=True)
payload = {"percent": int(percent), "stage": stage, "detail": detail}
fd, temp_path = tempfile.mkstemp(
    dir=os.path.dirname(path), prefix=".bootstrap-", suffix=".json"
)
with os.fdopen(fd, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, sort_keys=True)
os.replace(temp_path, path)
PY
}

# Never turn a real bootstrap failure into an opaque restart loop. Keep the
# truthful status surface alive long enough for a judge or operator to inspect
# the exact local diagnostic, then allow normal process cleanup when it stops.
fatal_bootstrap() {
  code="$1"
  phase="$2"
  diagnostic="$3"
  status 100 "Real DataHub bootstrap stopped" "$phase failed; the diagnostic is retained for inspection."
  {
    printf 'phase=%s\nexit_code=%s\n' "$phase" "$code"
    cat "$diagnostic" 2>/dev/null || true
  } > /app/state/bootstrap-failure.log
  while kill -0 "$BOOT_PID" >/dev/null 2>&1; do
    sleep 60
  done
  exit "$code"
}

# Emit only a bounded, redacted copy of a failed private bootstrap diagnostic
# into Cloudflare's authenticated container logs. The complete local file
# remains available inside the instance; this copy exists so operators can
# distinguish an import failure, an MCP handshake failure, and a GMS failure
# without adding an SSH key or public diagnostic endpoint.
emit_private_diagnostic() {
  phase="$1"
  attempt="$2"
  diagnostic="$3"
  python - "$phase" "$attempt" "$diagnostic" <<'PY' >&2
import hashlib
import re
import sys
from pathlib import Path

phase, attempt, raw_path = sys.argv[1:]
path = Path(raw_path)
raw = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
redacted = raw
patterns = (
    (r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?[^\s,;]+", r"\1[REDACTED]"),
    (r"(?i)\b(token|secret|password|api[_-]?key)\b(\s*[:=]\s*)[^\s,;]+", r"\1\2[REDACTED]"),
    (r"\b[A-Za-z0-9_-]{48,}\b", "[REDACTED-LONG-VALUE]"),
)
for pattern, replacement in patterns:
    redacted = re.sub(pattern, replacement, redacted)
lines = redacted.splitlines()[-160:]
digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
print(f"LINEAGE_PRIVATE_DIAGNOSTIC phase={phase} attempt={attempt} sha256={digest}")
print("\n".join(lines) if lines else "[diagnostic file was empty]")
print("LINEAGE_PRIVATE_DIAGNOSTIC_END")
PY
}

wait_http() {
  url="$1"
  attempts="$2"
  delay="$3"
  n=0
  until python - "$url" <<'PY' >/dev/null 2>&1
import sys
from urllib.request import urlopen

with urlopen(sys.argv[1], timeout=5) as response:
    if response.status < 200 or response.status >= 400:
        raise SystemExit(1)
PY
  do
    n=$((n + 1))
    if [ "$n" -ge "$attempts" ]; then
      echo "Timed out waiting for $url" >&2
      return 1
    fi
    sleep "$delay"
  done
}

wait_container_healthy() {
  name="$1"
  attempts="$2"
  delay="$3"
  n=0
  while :; do
    state="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$name" 2>/dev/null || true)"
    [ "$state" = "healthy" ] && return 0
    [ "$state" = "exited" ] && {
      docker logs "$name" --tail 120 >&2 || true
      return 1
    }
    n=$((n + 1))
    if [ "$n" -ge "$attempts" ]; then
      docker logs "$name" --tail 120 >&2 || true
      return 1
    fi
    sleep "$delay"
  done
}

cleanup() {
  for pull_pid in ${PULL_PIDS:-}; do
    kill "$pull_pid" >/dev/null 2>&1 || true
  done
  if [ -n "${BOOT_PID:-}" ]; then kill "$BOOT_PID" >/dev/null 2>&1 || true; fi
  if [ -n "${BRIDGE_PID:-}" ]; then kill "$BRIDGE_PID" >/dev/null 2>&1 || true; fi
  if [ -n "${DOCKERD_PID:-}" ]; then kill "$DOCKERD_PID" >/dev/null 2>&1 || true; fi
}
trap cleanup EXIT INT TERM

status 2 "Preparing the secure judge runtime" "Starting a visible, truthful progress surface."
python /app/cloudflare-fullstack/bootstrap_status.py &
BOOT_PID=$!

status 4 "Verifying the repair sandbox runtime" "Checking the POSIX semaphore path required by dbt-core."
SEMAPHORE_LOG="/app/state/semaphore-preflight.log"
if python -c 'import multiprocessing; multiprocessing.get_context("spawn").RLock()' \
    >"$SEMAPHORE_LOG" 2>&1
then
  :
else
  semaphore_code=$?
  fatal_bootstrap "$semaphore_code" "dbt semaphore preflight" "$SEMAPHORE_LOG"
fi

mkdir -p "$XDG_RUNTIME_DIR" /home/lineage/.local/share/docker
chmod 700 "$XDG_RUNTIME_DIR"

# Cloudflare Containers do not expose /dev/fuse to this unprivileged runtime.
# Let the same image use fuse-overlayfs where that device is genuinely
# available, otherwise use the kernel overlay driver. The vfs fallback copies
# each layer and exceeds the platform's effective inner-Docker quota.
if [ -c /dev/fuse ] && [ -r /dev/fuse ] && [ -w /dev/fuse ]; then
  DOCKER_STORAGE_DRIVER="fuse-overlayfs"
else
  DOCKER_STORAGE_DRIVER="overlay2"
fi
# A platform-level process restart can preserve the ephemeral filesystem while
# terminating every process. Remove only rootless Docker's stale PID/socket
# markers after proving no daemon is alive, so recovery does not require a
# fresh VM and never risks clobbering a running daemon.
if ! pgrep -x dockerd >/dev/null 2>&1; then
  rm -f "$XDG_RUNTIME_DIR/docker.pid" "$XDG_RUNTIME_DIR/docker.sock"
fi

status 6 "Starting the isolated DataHub runtime" "Launching rootless Docker with a platform-compatible shared namespace."
for required_command in dockerd docker newuidmap newgidmap rootlesskit; do
  command -v "$required_command" >/dev/null 2>&1 || {
    echo "Missing required rootless Docker command: $required_command" >&2
    exit 1
  }
done
rootlesskit \
  --net=host \
  --copy-up=/etc \
  --copy-up=/run \
  dockerd \
  --host="$DOCKER_HOST" \
  --iptables=false \
  --ip6tables=false \
  --bridge=none \
  --ip-forward=false \
  --ip-masq=false \
  --storage-driver="$DOCKER_STORAGE_DRIVER" \
  --data-root=/home/lineage/.local/share/docker \
  >/app/state/dockerd.log 2>&1 &
DOCKERD_PID=$!

n=0
until /opt/datahub-sidecar/bin/python -c '
import socket
sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.settimeout(1)
sock.connect("/home/lineage/.docker/run/docker.sock")
sock.sendall(b"GET /_ping HTTP/1.0\r\n\r\n")
data = sock.recv(256)
sock.close()
raise SystemExit(0 if b"200" in data else 1)
' >/dev/null 2>&1; do
  n=$((n + 1))
  [ "$n" -ge 300 ] && {
    tail -n 160 /app/state/dockerd.log >&2 || true
    exit 1
  }
  sleep 0.2
done

# A process restart inside the same Cloudflare VM can retain the rootless
# daemon's ephemeral data. Remove only this application's explicitly named
# service containers so startup is repeatable rather than failing on a stale
# name from an interrupted boot.
for service_name in \
  lineage-gms lineage-kafka lineage-opensearch lineage-mysql lineage-net
do
  docker rm -f "$service_name" >/dev/null 2>&1 || true
done

PULL_DIR="/app/state/image-pulls"
PULL_LABELS="mysql opensearch kafka datahub-upgrade datahub-gms bridge"
PULL_PIDS=""
mkdir -p "$PULL_DIR"

pull_image() {
  label="$1"
  image="$2"
  rm -f "$PULL_DIR/$label.exit" "$PULL_DIR/$label.log"
  (
    code=0
    docker pull "$image" >"$PULL_DIR/$label.log" 2>&1 || code=$?
    printf '%s\n' "$code" >"$PULL_DIR/$label.exit"
  ) &
  PULL_PIDS="$PULL_PIDS $!"
}

status 12 "Loading the official DataHub services" "Fetching six digest-pinned runtime images in parallel."
pull_image mysql "$MYSQL_IMAGE"
pull_image opensearch "$OPENSEARCH_IMAGE"
pull_image kafka "$KAFKA_IMAGE"
pull_image datahub-upgrade "$DATAHUB_UPGRADE_IMAGE"
pull_image datahub-gms "$DATAHUB_GMS_IMAGE"
pull_image bridge "$BRIDGE_IMAGE"

completed=0
while [ "$completed" -lt 6 ]; do
  completed=0
  pending=""
  for label in $PULL_LABELS; do
    if [ -f "$PULL_DIR/$label.exit" ]; then
      completed=$((completed + 1))
    else
      pending="$pending $label"
    fi
  done
  percent=$((12 + completed * 2))
  [ "$percent" -le 26 ] || percent=26
  status "$percent" "Loading the official DataHub services" \
    "$completed of 6 pinned images verified. Active:$pending"
  [ "$completed" -ge 6 ] || sleep 1
done
PULL_PIDS=""

for label in $PULL_LABELS; do
  code="$(cat "$PULL_DIR/$label.exit")"
  if [ "$code" -ne 0 ]; then
    fatal_bootstrap "$code" "Pinned image pull: $label" "$PULL_DIR/$label.log"
  fi
done

BRIDGE_SOCKET="/app/state/datahub-gms.sock"
rm -f "$BRIDGE_SOCKET"
status 27 "Opening the private DataHub service lane" "Creating one permitted namespace and a Unix-socket bridge to GMS."
NAMESPACE_START_LOG="/app/state/namespace-start.log"
if docker run -d --name lineage-net --network none \
    -v /app/cloudflare-fullstack/net_bridge.py:/opt/lineage/net_bridge.py:ro \
    -v /app/state:/shared \
    "$BRIDGE_IMAGE" \
    python /opt/lineage/net_bridge.py inner \
      --unix-path /shared/datahub-gms.sock \
      --target-host 127.0.0.1 \
      --target-port 8080 >"$NAMESPACE_START_LOG" 2>&1
then
  :
else
  namespace_start_code=$?
  fatal_bootstrap "$namespace_start_code" "DataHub namespace bridge start" "$NAMESPACE_START_LOG"
fi
n=0
until [ -S "$BRIDGE_SOCKET" ]; do
  n=$((n + 1))
  [ "$n" -ge 100 ] && fatal_bootstrap 1 "DataHub namespace bridge socket" "$NAMESPACE_START_LOG"
  sleep 0.1
done
python /app/cloudflare-fullstack/net_bridge.py outer \
  --unix-path "$BRIDGE_SOCKET" \
  --listen-host 127.0.0.1 \
  --listen-port 8080 \
  >/app/state/gms-bridge.log 2>&1 &
BRIDGE_PID=$!
status 28 "Starting durable catalog storage" "Bringing up the real DataHub SQL metadata store."
MYSQL_START_LOG="/app/state/mysql-start.log"
if docker run -d --name lineage-mysql --network container:lineage-net \
  -e MYSQL_DATABASE=datahub \
  -e MYSQL_PASSWORD="$MYSQL_PASSWORD" \
  -e MYSQL_ROOT_HOST=% \
  -e MYSQL_ROOT_PASSWORD="$MYSQL_ROOT_PASSWORD" \
  -e MYSQL_USER=datahub \
  --health-cmd="mysqladmin ping -h 127.0.0.1 -u datahub --password=$MYSQL_PASSWORD" \
  --health-interval=2s --health-timeout=10s --health-retries=20 --health-start-period=20s \
  "$MYSQL_IMAGE" \
  --character-set-server=utf8mb4 \
  --collation-server=utf8mb4_bin \
  --default-authentication-plugin=caching_sha2_password >"$MYSQL_START_LOG" 2>&1
then
  :
else
  mysql_start_code=$?
  fatal_bootstrap "$mysql_start_code" "MySQL container start" "$MYSQL_START_LOG"
fi
if ! wait_container_healthy lineage-mysql 90 2; then
  docker logs lineage-mysql --tail 160 > /app/state/mysql-health.log 2>&1 || true
  fatal_bootstrap 1 "MySQL health check" "/app/state/mysql-health.log"
fi

status 38 "Starting the context index" "Opening the real OpenSearch graph and search layer."
docker run -d --name lineage-opensearch --network container:lineage-net \
  -e DISABLE_SECURITY_PLUGIN=true \
  -e discovery.type=single-node \
  -e 'OPENSEARCH_JAVA_OPTS=-Xms768m -Xmx1024m -Dlog4j2.formatMsgNoLookups=true' \
  --health-cmd='curl -fsS http://127.0.0.1:9200/_cluster/health?wait_for_status=yellow&timeout=0s' \
  --health-interval=5s --health-timeout=15s --health-retries=24 --health-start-period=60s \
  "$OPENSEARCH_IMAGE"
wait_container_healthy lineage-opensearch 90 3

status 48 "Starting the metadata event bus" "Launching Kafka for DataHub change events and graph updates."
docker run -d --name lineage-kafka --network container:lineage-net \
  -e KAFKA_ADVERTISED_LISTENERS='BROKER://127.0.0.1:29092,EXTERNAL://127.0.0.1:9092' \
  -e KAFKA_BROKER_ID=1 \
  -e KAFKA_CONFLUENT_SUPPORT_METRICS_ENABLE=false \
  -e KAFKA_CONTROLLER_LISTENER_NAMES=CONTROLLER \
  -e KAFKA_CONTROLLER_QUORUM_VOTERS='1@127.0.0.1:39092' \
  -e KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS=0 \
  -e KAFKA_HEAP_OPTS='-Xms512m -Xmx512m' \
  -e KAFKA_INTER_BROKER_LISTENER_NAME=BROKER \
  -e KAFKA_LISTENER_SECURITY_PROTOCOL_MAP='CONTROLLER:PLAINTEXT,BROKER:PLAINTEXT,EXTERNAL:PLAINTEXT' \
  -e KAFKA_LISTENERS='BROKER://0.0.0.0:29092,EXTERNAL://0.0.0.0:9092,CONTROLLER://0.0.0.0:39092' \
  -e KAFKA_MAX_MESSAGE_BYTES=5242880 \
  -e KAFKA_MESSAGE_MAX_BYTES=5242880 \
  -e KAFKA_NODE_ID=1 \
  -e KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR=1 \
  -e KAFKA_PROCESS_ROLES='controller,broker' \
  --health-cmd='nc -z 127.0.0.1 9092' \
  --health-interval=2s --health-timeout=5s --health-retries=40 --health-start-period=60s \
  "$KAFKA_IMAGE" \
  /bin/bash -c '
    file_path=/var/lib/kafka/data/clusterID
    if [ ! -f "$file_path" ]; then
      /bin/kafka-storage random-uuid > "$file_path"
      kafka-storage format --ignore-formatted -t "$(cat "$file_path")" -c /etc/kafka/kafka.properties
    fi
    export CLUSTER_ID="$(cat "$file_path")"
    exec /etc/confluent/docker/run
  '
wait_container_healthy lineage-kafka 100 3

COMMON_ENV="
  -e DATAHUB_BASE_PATH=/
  -e DATAHUB_GMS_BASE_PATH=/
  -e DATAHUB_TOKEN_SERVICE_SALT=$TOKEN_SERVICE_SALT
  -e DATAHUB_TOKEN_SERVICE_SIGNING_KEY=$TOKEN_SERVICE_SIGNING_KEY
  -e EBEAN_DATASOURCE_DRIVER=com.mysql.jdbc.Driver
  -e EBEAN_DATASOURCE_HOST=127.0.0.1:3306
  -e EBEAN_DATASOURCE_PASSWORD=$MYSQL_PASSWORD
  -e EBEAN_DATASOURCE_URL=jdbc:mysql://127.0.0.1:3306/datahub?verifyServerCertificate=false&useSSL=false&useUnicode=yes&characterEncoding=UTF-8
  -e EBEAN_DATASOURCE_USERNAME=datahub
  -e ELASTICSEARCH_HOST=127.0.0.1
  -e ELASTICSEARCH_IMPLEMENTATION=opensearch
  -e ELASTICSEARCH_PORT=9200
  -e ELASTICSEARCH_PROTOCOL=http
  -e ELASTICSEARCH_USE_SSL=false
  -e ENTITY_REGISTRY_CONFIG_PATH=/datahub/datahub-gms/resources/entity-registry.yml
  -e ENTITY_VERSIONING_ENABLED=true
  -e GRAPH_SERVICE_IMPL=elasticsearch
  -e KAFKA_BOOTSTRAP_SERVER=127.0.0.1:29092
  -e KAFKA_SCHEMAREGISTRY_URL=http://127.0.0.1:8080/schema-registry/api/
  -e SCHEMA_REGISTRY_TYPE=INTERNAL
"

status 60 "Building the DataHub metadata model" "Running the official pinned DataHub system migration."
# shellcheck disable=SC2086
docker run --rm --network container:lineage-net $COMMON_ENV \
  -e BACKFILL_BROWSE_PATHS_V2=true \
  -e DATAHUB_GMS_HOST=127.0.0.1 \
  -e DATAHUB_GMS_PORT=8080 \
  -e DATAHUB_PRECREATE_TOPICS=true \
  -e DATAHUB_SQL_SETUP_ENABLED=true \
  -e ELASTICSEARCH_BUILD_INDICES_CLONE_INDICES=false \
  -e ELASTICSEARCH_INDEX_BUILDER_MAPPINGS_REINDEX=true \
  -e ELASTICSEARCH_INDEX_BUILDER_REFRESH_INTERVAL_SECONDS=3 \
  -e ELASTICSEARCH_INDEX_BUILDER_SETTINGS_REINDEX=true \
  -e PARTITIONS=3 \
  -e SCHEMA_REGISTRY_SYSTEM_UPDATE=true \
  -e SPRING_KAFKA_PROPERTIES_AUTO_REGISTER_SCHEMAS=true \
  -e SPRING_KAFKA_PROPERTIES_USE_LATEST_VERSION=true \
  -e USE_CONFLUENT_SCHEMA_REGISTRY=false \
  "$DATAHUB_UPGRADE_IMAGE" -u SystemUpdate

status 72 "Starting DataHub GMS" "Opening the real GraphQL, lineage, entity, and mutation surfaces."
# shellcheck disable=SC2086
docker run -d --name lineage-gms --network container:lineage-net $COMMON_ENV \
  -e ALTERNATE_MCP_VALIDATION=true \
  -e CONFIG_ENTITY_REGISTRY_USE_OPTIMIZED_LOADING=true \
  -e DATAHUB_SERVER_TYPE=quickstart \
  -e DATAHUB_TELEMETRY_ENABLED=false \
  -e ELASTICSEARCH_INDEX_BUILDER_MAPPINGS_REINDEX=true \
  -e ELASTICSEARCH_INDEX_BUILDER_SETTINGS_REINDEX=true \
  -e ELASTICSEARCH_LIMIT_RESULTS_STRICT=true \
  -e ENTITY_SERVICE_ENABLE_RETENTION=true \
  -e ES_BULK_REFRESH_POLICY=WAIT_UNTIL \
  -e EXTRACT_JAR_ENABLED=true \
  -e GRAPH_SERVICE_DIFF_MODE_ENABLED=true \
  -e JAVA_OPTS='-Xms1g -Xmx1g' \
  -e MAE_CONSUMER_ENABLED=true \
  -e MCE_CONSUMER_ENABLED=true \
  -e METADATA_SERVICE_AUTH_ENABLED=false \
  -e PE_CONSUMER_ENABLED=true \
  -e SEARCH_BAR_API_VARIANT=SEARCH_ACROSS_ENTITIES \
  -e STRICT_URN_VALIDATION_ENABLED=true \
  --health-cmd='curl -fsS http://127.0.0.1:8080/health' \
  --health-interval=2s --health-timeout=5s --health-retries=60 --health-start-period=90s \
  "$DATAHUB_GMS_IMAGE"
wait_container_healthy lineage-gms 120 3
wait_http http://127.0.0.1:8080/health 30 2

status 84 "Planting the judge incident catalog" "Writing three real signal-driven incidents through the official DataHub SDK."
/opt/datahub-sidecar/bin/python /app/seed_demo.py
/opt/datahub-sidecar/bin/python /app/tools/setup_vocab_sidecar.py

status 92 "Proving MCP read and write paths" "Reading back entities, lineage, and mutation capability through the official MCP server."
JUDGE_CATALOG_DIAGNOSTIC=/app/state/judge-catalog-verification.log
JUDGE_CATALOG_VERIFIED=0
JUDGE_CATALOG_ATTEMPT=1
while [ "$JUDGE_CATALOG_ATTEMPT" -le 6 ]; do
  status 92 \
    "Proving MCP read and write paths" \
    "Verification attempt ${JUDGE_CATALOG_ATTEMPT} of 6: reading entities, lineage, and a reversible tag mutation through the official MCP server."
  VERIFY_EXIT=0
  # Keep production verification observable through its bounded receipt, but
  # do not enable the upstream server's full GraphQL payload logger. On a
  # container platform that volume can create log backpressure and turn a
  # healthy catalog proof into an artificial timeout.
  if LINEAGE_MCP_DEBUG=0 \
      /opt/datahub-sidecar/bin/python /app/tools/verify_judge_catalog.py \
      > /app/state/judge-catalog-receipt.json \
      2> "$JUDGE_CATALOG_DIAGNOSTIC"; then
    JUDGE_CATALOG_VERIFIED=1
    break
  else
    VERIFY_EXIT=$?
  fi
  emit_private_diagnostic \
    "official MCP catalog verification" \
    "$JUDGE_CATALOG_ATTEMPT" \
    "$JUDGE_CATALOG_DIAGNOSTIC"
  if [ "$VERIFY_EXIT" -ne 75 ]; then
    fatal_bootstrap "$VERIFY_EXIT" \
      "official MCP catalog verification" \
      "$JUDGE_CATALOG_DIAGNOSTIC"
  fi
  if [ "$JUDGE_CATALOG_ATTEMPT" -lt 6 ]; then
    status 92 \
      "Rechecking the official MCP path" \
      "A transient verification attempt failed. DataHub remains running; retrying the real read/write proof without restarting the stack."
    sleep $((JUDGE_CATALOG_ATTEMPT * 5))
  fi
  JUDGE_CATALOG_ATTEMPT=$((JUDGE_CATALOG_ATTEMPT + 1))
done
if [ "$JUDGE_CATALOG_VERIFIED" -ne 1 ]; then
  fatal_bootstrap 1 "official MCP catalog verification" "$JUDGE_CATALOG_DIAGNOSTIC"
fi

status 98 "Opening Lineage Detective" "The real DataHub-backed judge workspace is ready."
kill "$BOOT_PID" >/dev/null 2>&1 || true
wait "$BOOT_PID" 2>/dev/null || true
BOOT_PID=

exec python -m streamlit run /app/app.py \
  --server.address=0.0.0.0 \
  --server.port=8501 \
  --server.headless=true
