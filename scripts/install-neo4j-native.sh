#!/usr/bin/env bash
# Install Neo4j Community 5.26 LTS natively on Ubuntu (22.04+), with the free APOC and
# Graph Data Science plugins, and set the initial password from .env (NEO4J_PASSWORD).
#
# Usage:  sudo -v && bash scripts/install-neo4j-native.sh
# Idempotent: re-running upgrades/repairs in place. Needs sudo for apt and /etc/neo4j.
set -euo pipefail

NEO4J_SERIES="${NEO4J_SERIES:-5.26}"           # LTS line
GDS_VERSION="${GDS_VERSION:-2.13.4}"             # GDS 2.13.x is the line built for Neo4j 5.26
CONF=/etc/neo4j/neo4j.conf
PLUGINS=/var/lib/neo4j/plugins

cd "$(dirname "$0")/.."
if [ -f .env ]; then
  # shellcheck disable=SC1091
  set -a; . ./.env; set +a
fi
NEO4J_PASSWORD="${NEO4J_PASSWORD:-osintree-dev}"

say() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }

say "Installing Java 21 and helpers"
sudo apt-get update -qq
sudo apt-get install -y -qq wget gnupg curl openjdk-21-jre-headless

say "Adding the Neo4j apt repository (stable ${NEO4J_SERIES%%.*})"
sudo install -d -m 0755 /etc/apt/keyrings
wget -qO - https://debian.neo4j.com/neotechnology.gpg.key \
  | sudo gpg --dearmor --yes -o /etc/apt/keyrings/neotechnology.gpg
echo "deb [signed-by=/etc/apt/keyrings/neotechnology.gpg] https://debian.neo4j.com stable ${NEO4J_SERIES%%.*}" \
  | sudo tee /etc/apt/sources.list.d/neo4j.list >/dev/null
sudo apt-get update -qq

say "Installing the latest Neo4j ${NEO4J_SERIES}.x"
LATEST="$(apt-cache madison neo4j | awk '{print $3}' | grep "^1:${NEO4J_SERIES}\." | sort -V | tail -1)"
if [ -z "$LATEST" ]; then echo "no neo4j ${NEO4J_SERIES}.x package found" >&2; exit 1; fi
sudo apt-get install -y -qq "neo4j=${LATEST}"
sudo apt-mark hold neo4j >/dev/null
NEO4J_VERSION="${LATEST#1:}"
echo "installed neo4j ${NEO4J_VERSION}"

say "Installing APOC ${NEO4J_VERSION} and GDS ${GDS_VERSION} into ${PLUGINS}"
sudo rm -f "${PLUGINS}"/apoc-*.jar "${PLUGINS}"/neo4j-graph-data-science-*.jar
sudo wget -q -O "${PLUGINS}/apoc-${NEO4J_VERSION}-core.jar" \
  "https://github.com/neo4j/apoc/releases/download/${NEO4J_VERSION}/apoc-${NEO4J_VERSION}-core.jar"
sudo wget -q -O "${PLUGINS}/neo4j-graph-data-science-${GDS_VERSION}.jar" \
  "https://github.com/neo4j/graph-data-science/releases/download/${GDS_VERSION}/neo4j-graph-data-science-${GDS_VERSION}.jar"
sudo chown neo4j:neo4j "${PLUGINS}"/*.jar

say "Configuring ${CONF}"
set_conf() {  # set_conf key value  -> replaces or appends key=value
  local key="$1" value="$2"
  if sudo grep -qE "^#?${key}=" "$CONF"; then
    sudo sed -i -E "s|^#?${key}=.*|${key}=${value}|" "$CONF"
  else
    echo "${key}=${value}" | sudo tee -a "$CONF" >/dev/null
  fi
}
set_conf server.default_listen_address 127.0.0.1
set_conf dbms.security.procedures.unrestricted "apoc.*,gds.*"
set_conf dbms.security.procedures.allowlist "apoc.*,gds.*"
set_conf server.memory.heap.initial_size 512m
set_conf server.memory.heap.max_size 1G
set_conf server.memory.pagecache.size 256m

say "Setting the initial password (only works before first start; otherwise unchanged)"
sudo systemctl stop neo4j >/dev/null 2>&1 || true
if ! sudo -u neo4j neo4j-admin dbms set-initial-password "$NEO4J_PASSWORD" 2>/dev/null; then
  echo "  password already set earlier; keeping it. Change it in Neo4j Browser if needed."
fi

say "Enabling and starting the neo4j service"
sudo systemctl enable --now neo4j
for _ in $(seq 1 30); do
  if curl -fs http://localhost:7474 >/dev/null 2>&1; then break; fi
  sleep 2
done

say "Verifying credentials and plugins"
if command -v cypher-shell >/dev/null; then
  if ! cypher-shell -u neo4j -p "$NEO4J_PASSWORD" "RETURN 1" >/dev/null 2>&1; then
    # Neo4j had already been started once with the factory password: rotate it now.
    if cypher-shell -u neo4j -p neo4j -d system \
         "ALTER CURRENT USER SET PASSWORD FROM 'neo4j' TO '$NEO4J_PASSWORD'" >/dev/null 2>&1; then
      echo "  factory password replaced with the one from .env"
    else
      echo "  could not log in with the .env password nor the factory one;" \
           "set NEO4J_PASSWORD in .env to the current password" >&2
    fi
  fi
  cypher-shell -u neo4j -p "$NEO4J_PASSWORD" \
    "RETURN apoc.version() AS apoc, gds.version() AS gds" || \
    echo "  (plugin check failed; open http://localhost:7474 and run RETURN apoc.version(), gds.version())"
fi

echo
echo "Done. Neo4j Browser: http://localhost:7474  (user neo4j / password from .env)"
echo "Set NEO4J_MODE=native in .env so 'make up' / 'make down' use systemctl."
