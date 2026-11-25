#!/usr/bin/env python3
# template-managed: addons/deploy/scripts/deploy.py — edit in _Claude-Template, not here
"""deploy — the project's half of the shared CD (`.github/workflows/cd.yml`), and its check.

The workflow is byte-identical in every project, and docker-compose.yml is the one source of what
differs — nothing is declared twice:

  values    every `${NAME}` in the file. Without a default (`${NAME}`, `${NAME:?…}`) it must exist in
            the GitHub environment `prod` (secret first, then variable); with one (`${NAME:-…}`) it is
            written when set. CD itself provides APP_VERSION (the tag), APP_PORT (a variable) and
            DATA_DIR (below).
  service   the one publishing `127.0.0.1:${APP_PORT…}:N`. After `up -d` CD waits on its compose
            `healthcheck:` alone (Docker's own status: healthy → go on; unhealthy, exited or a restart
            loop → roll back) — not `up --wait`, which waits for every service and would fail a deploy
            whose app stops one of its own helpers on start. Then one GET on the health path must
            report the released version. The block, the same in every project — a 2 s probe while
            starting, so the deploy waits as long as the app needs; 30 s afterwards, which `docker ps` shows:
                healthcheck:
                  test: ["CMD", "python", "-c", "<GET /health with urllib, timeout 4>"]   # node: fetch()
                  interval: 30s
                  timeout: 5s
                  retries: 3
                  start_period: 60s
                  start_interval: 2s
  dir       /srv/<group>/<name> — or /srv/<name> without a group. `name:` must be the repo's own name,
            lower-case: repo, compose project and server dir are one name and cannot drift apart.
  data      /srv/<group>/data — or /srv/<name>/data. Every bit of state is bind-mounted from
            `${DATA_DIR:-./data}/…`, so one folder is the whole backup and a redeploy never touches it;
            locally it is ./data. A `./folder`, a named volume or a /srv path is refused.
  files     docker-compose.yml + every repo file bind-mounted as `./path:`.
  x-deploy  the file's own block, both optional:  x-deploy:
                                                     group: zebaro-core    (several repos, one product)
                                                     health: /api/health   (default /health)

  lint (default)   the gate check — the file follows the standard: `name:` = the repo's name; every
                   published port `127.0.0.1:${APP_PORT…}:N`, exactly one service on APP_PORT; that
                   service has a `healthcheck:` and the image `<image>:${APP_VERSION…}`, never a fixed
                   tag; no bare pass-through
                   in `environment:` (`- NAME` reads the shell, and CD has none — `- NAME=${NAME}`);
                   state only under ${DATA_DIR}. A line ending in `# deploy-lint: allow` is exempt.
  bundle <out>     CD only: <out>/ gets the files, `.env` (mode 600), `.ghcr` (the pull token) and
                   `.deploy.sh` — what the server runs, one deploy at a time per server: install →
                   up → the service healthy → health reports the version → else the previous compose and
                   .env come back.
  get <key>        one value for the workflow: dir, service, health or data.

Exit 0 = clean, 1 = violations / missing values, 2 = no compose file. Stdlib only.
"""

import contextlib
import json
import os
import re
import shlex
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPOSE = "docker-compose.yml"
PROVIDED = {"APP_VERSION", "APP_PORT", "DATA_DIR"}  # CD writes these itself
SYSTEM_MOUNTS = ("/var/run/docker.sock", "/lib/modules", "/etc/localtime", "/etc/timezone")
REF_RE = re.compile(r"(?<!\$)\$\{([A-Za-z_][A-Za-z0-9_]*)(:?[-?+][^}]*)?\}")
PORT_RE = re.compile(r"^127\.0\.0\.1:\$\{APP_PORT(:-\d+)?\}:\d+(/tcp)?$")
ALLOW = "# deploy-lint: allow"

for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):  # a stream that cannot be reconfigured stays as it is
        _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]


def parse(root=None):
    """Read docker-compose.yml line by line (no YAML in the stdlib) → a dict, or None when missing."""
    root = root or ROOT
    try:
        with open(os.path.join(root, COMPOSE), encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return None
    c = {"name": None, "x": {}, "services": {}, "lines": lines, "problems": [], "mounts": [], "refs": {}}
    section, svc_indent, current, block, block_indent, vol_indent = None, None, None, None, -1, None
    for no, raw in enumerate(lines, 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        allowed = raw.rstrip().endswith(ALLOW)
        line = raw.split(" #")[0].rstrip()
        indent = len(line) - len(line.lstrip())
        stripped = line.strip()
        where = f"{COMPOSE}:{no}"
        if not allowed:
            for name, mod in REF_RE.findall(line):
                required = not mod or mod.lstrip(":").startswith("?")
                c["refs"][name] = c["refs"].get(name, False) or required
        if indent == 0:
            section = stripped.split(":")[0]
            m = re.match(r"^name:\s*['\"]?([\w.-]+)['\"]?\s*$", line)
            if m:
                c["name"] = m.group(1)
            current, block = None, None
            continue
        if section == "x-deploy":
            m = re.match(r"^\s+(health|group):\s*['\"]?(\S+?)['\"]?\s*$", line)
            if m:
                c["x"][m.group(1)] = m.group(2)
            continue
        if section == "volumes" and not allowed:
            m = re.match(r"^\s+([\w.-]+):", line)
            if m and (vol_indent is None or indent == vol_indent):
                vol_indent = indent
                c["problems"].append(
                    f"{where}: named volume `{m.group(1)}` — state lives in"
                    " ${DATA_DIR:-./data}/<folder>, the one folder that is backed up"
                )
            continue
        if section != "services":
            continue
        m = re.match(r"^\s+([\w.-]+):\s*$", line)
        if m and (svc_indent is None or indent == svc_indent):
            svc_indent, current, block = indent, m.group(1), None
            c["services"][current] = {"ports": [], "image": None, "line": where, "healthcheck": False}
            continue
        if current is None:
            continue
        if block and (indent < block_indent or (indent == block_indent and not stripped.startswith("-"))):
            block = None  # YAML lets a list sit at its key's indent: `ports:` / `- "…"` stay one block
        m = re.match(r"^\s+(ports|environment|volumes):\s*$", line)
        if m:
            block, block_indent = m.group(1), indent
            continue
        if re.match(r"^\s+healthcheck:\s*$", line) and indent > (svc_indent or 0):
            c["services"][current]["healthcheck"] = True
            continue
        m = re.match(r"^\s+image:\s*['\"]?(\S+?)['\"]?\s*$", line)
        if m and indent > (svc_indent or 0):
            c["services"][current]["image"] = (where, m.group(1))
            continue
        item = re.sub(r"^-\s*", "", stripped).strip("'\"")
        if block == "ports":
            c["services"][current]["ports"].append((where, item, allowed))
        elif block == "volumes" and not allowed:
            source = item.split(":")[0]
            if source.startswith("./") and os.path.isfile(os.path.join(root, source[2:])):
                c["mounts"].append(source[2:])  # a repo file: CD copies it next to the compose file
            elif source.startswith("${DATA_DIR") or source.startswith(SYSTEM_MOUNTS) or ":" not in item:
                pass
            elif source.startswith(("./", "../", "/srv/")):
                c["problems"].append(
                    f"{where}: `{source}` — state goes under ${{DATA_DIR:-./data}}/<folder>"
                    " (a repo file mounted as ./path is fine)"
                )
            elif not source.startswith(("/", "~", "$")):
                c["problems"].append(
                    f"{where}: named volume `{source}` — state lives in"
                    " ${DATA_DIR:-./data}/<folder>, the one folder that is backed up"
                )
        elif block == "environment" and not allowed:
            if re.match(r"^-\s*[A-Za-z_][A-Za-z0-9_]*$", stripped):
                c["problems"].append(
                    f"{where}: `- {item}` takes the value from the shell, and CD has none —"
                    f" write `- {item}=${{{item}}}` (or with a default)"
                )
            elif re.match(r"^[A-Za-z_][A-Za-z0-9_]*:$", stripped):
                name = stripped[:-1]
                c["problems"].append(f"{where}: `{stripped}` has no value — write `{name}: ${{{name}}}`")
    return c


def repo_name(root=None):
    """The repo's name, lower-case: GitHub's in CI, the folder's locally (a clone keeps it)."""
    repo = os.environ.get("GITHUB_REPOSITORY", "").rpartition("/")[2]
    return (repo or os.path.basename(os.path.abspath(root or ROOT))).lower()


def facts(c, root=None):
    """{dir, data, service, health, files} derived from the parsed file; a value is None when underivable."""
    root = root or ROOT
    on_port = [s for s, v in c["services"].items() if any("${APP_PORT" in p for _, p, _ in v["ports"])]
    group, name = c["x"].get("group"), c["name"]
    base = f"/srv/{group}" if group else (f"/srv/{name}" if name else None)
    return {
        "dir": (f"{base}/{name}" if group else base) if name else None,
        "data": f"{base}/data" if base else None,
        "service": on_port[0] if len(on_port) == 1 else None,
        "health": c["x"].get("health", "/health"),
        "files": [COMPOSE, *sorted({m for m in c["mounts"] if os.path.isfile(os.path.join(root, m))})],
    }


def lint(c, root=None):
    if c is None:
        return [f"{COMPOSE}: missing"]
    errors = list(c["problems"])
    repo = repo_name(root)
    if not c["name"]:
        errors.append(f"{COMPOSE}: no top-level `name:` — write `name: {repo}` (the compose project and /srv/{repo})")
    elif c["name"] != repo:
        errors.append(
            f"{COMPOSE}: `name: {c['name']}` — must be the repo's name, `{repo}`: the compose project"
            f" and the server dir /srv/{repo} follow it"
        )
    for v in c["services"].values():
        for where, item, allowed in v["ports"]:
            if not allowed and not PORT_RE.match(item):
                errors.append(
                    f'{where}: port {item!r} — publish as "127.0.0.1:${{APP_PORT:-<port>}}:<container port>"'
                    " (Docker publishes past the host firewall; the tunnel reaches localhost)"
                )
    f = facts(c, root)
    service, health, group = f["service"], f["health"], c["x"].get("group")
    if group is not None and not re.match(r"^[a-z0-9][a-z0-9._-]*$", group):
        errors.append(f"{COMPOSE}: x-deploy.group {group!r} — a lower-case folder name, e.g. zebaro-core")
    on_port = [s for s, v in c["services"].items() if any("${APP_PORT" in p for _, p, _ in v["ports"])]
    if len(on_port) != 1:
        errors.append(
            f"{COMPOSE}: {len(on_port)} services publish ${{APP_PORT}} ({', '.join(on_port) or 'none'})"
            " — exactly one: the service CD checks"
        )
    if service:
        where, image = c["services"][service]["image"] or (c["services"][service]["line"], "")
        if "${APP_VERSION" not in image:
            errors.append(
                f"{where}: {service} image {image or '(none)'} — the release runs its own tag:"
                " <image>:${APP_VERSION:-latest}"
            )
        if not c["services"][service].get("healthcheck"):
            errors.append(
                f"{c['services'][service]['line']}: {service} has no `healthcheck:` — CD waits for it,"
                f" and `docker ps` shows it (test: GET {health} inside the container)"
            )
    if not health.startswith("/") or "'" in health:
        errors.append(f"{COMPOSE}: x-deploy.health {health!r} — a path, e.g. /health")
    return errors


def cmd_lint():
    c = parse()
    if c is None:
        print(f"deploy: no {COMPOSE}")
        return 2
    errors = lint(c)
    for e in errors:
        print(f"  ✗ {e}")
    if errors:
        print(f"deploy: {len(errors)} problem(s)")
        return 1
    f = facts(c)
    names = sorted(set(c["refs"]) - PROVIDED)
    print(
        f"deploy: standard ok — {f['service']} → {f['dir']}, data {f['data']}, health {f['health']},"
        f" {len(f['files'])} file(s), {len(names)} value(s)"
    )
    return 0


REMOTE = r"""#!/usr/bin/env bash
# Written by scripts/deploy.py bundle — runs on the server from <dir>/.incoming.
set -euo pipefail
DIR=__DIR__; SERVICE=__SERVICE__; HEALTH=__HEALTH__; VERSION=__VERSION__; PORT=__PORT__; GHCR_USER=__USER__
FILES=(__FILES__)
cd "$DIR"
umask 077
# The pull token and its login never outlive this run, whichever way it ends.
trap 'rm -rf "$DIR/.incoming"' EXIT

# One deploy at a time on this server, whatever the repo: two `compose up`s, a shared network and
# `image prune` do not like company. The next one waits up to 10 minutes.
if command -v flock >/dev/null; then
  exec 9>"${TMPDIR:-/tmp}/deploy-$(id -u).lock"
  echo "waiting for the server's deploy lock…"
  flock -w 600 9 || { echo "::error::another deploy held the server for 10 minutes"; exit 1; }
fi

# This deploy's own registry login: every project here deploys as the same user, and a `logout` in
# another project's run would otherwise pull the credentials from under this pull.
export DOCKER_CONFIG="$DIR/.incoming/docker"
mkdir -p "$DOCKER_CONFIG"

# Waits on the compose healthcheck of $SERVICE alone — as long as the app needs to come up, not a fixed
# timer. Not `up --wait`: that waits for every service, and a project may stop its own helpers on start
# (the bot stops an infra switched off in /services), which would read as a failed deploy.
ready() {
  local cid state health restarts i
  for i in $(seq 1 120); do  # 2 s steps; the healthcheck's start_period and retries end it far sooner
    cid=$(docker compose ps -aq "$SERVICE")
    state=$(docker inspect -f '{{.State.Status}}' "$cid" 2>/dev/null || echo missing)
    health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid" \
      2>/dev/null || echo missing)
    restarts=$(docker inspect -f '{{.RestartCount}}' "$cid" 2>/dev/null || echo 0)
    case "$health" in
      healthy) return 0 ;;
      unhealthy) echo "$SERVICE is unhealthy"; return 1 ;;
      none) echo "$SERVICE has no healthcheck"; return 1 ;;
    esac
    case "$state" in exited|dead|missing) echo "$SERVICE is $state"; return 1 ;; esac
    if [ "$restarts" -gt 2 ]; then echo "$SERVICE restarts in a loop ($restarts)"; return 1; fi
    sleep 2
  done
  echo "$SERVICE did not become healthy in 4 minutes"
  return 1
}

# Then one look from the outside: the port cloudflared uses answers, with the version just released
# (not an old container that happened to be healthy).
healthy() {  # healthy <version>
  local want="$1" body="" i cid restarts
  for i in 1 2 3; do
    body=$(curl -fsS -m 5 "http://127.0.0.1:${PORT}${HEALTH}" 2>/dev/null || true)
    if printf '%s' "$body" | grep -Eq "\"version\": ?\"${want//./\\.}\""; then
      cid=$(docker compose ps -q "$SERVICE")
      restarts=$(docker inspect -f '{{.RestartCount}}' "$cid" 2>/dev/null || echo 99)
      if [ "$restarts" -le 1 ]; then echo "health: $body"; return 0; fi
      echo "$SERVICE restarted $restarts times"; return 1
    fi
    sleep 2
  done
  echo "health on 127.0.0.1:${PORT}${HEALTH} did not report $want: ${body:-no answer}"
  return 1
}

# What runs now is kept — the rollback brings exactly this back.
rm -rf .previous && mkdir .previous
for f in .env "${FILES[@]}"; do if [ -e "$f" ]; then cp -p --parents "$f" .previous/; fi; done
previous=$(sed -n "s/^APP_VERSION='\{0,1\}\([^']*\)'\{0,1\}$/\1/p" .previous/.env 2>/dev/null || true)

for f in "${FILES[@]}"; do mkdir -p "$(dirname "$f")"; cp -p ".incoming/$f" "$f"; done
cp -p .incoming/.env .env
docker login ghcr.io -u "$GHCR_USER" --password-stdin < .incoming/.ghcr >/dev/null
rm -f .incoming/.ghcr

echo "deploying $VERSION (running before: ${previous:-unknown})"
if docker compose up -d --pull always && ready && healthy "$VERSION"; then
  docker image prune -f >/dev/null || true  # never fail a deploy on another project's prune
  echo "deployed $VERSION"
  exit 0
fi

echo "::error::$VERSION did not come up healthy"
docker compose logs --tail 80 "$SERVICE" || true
if [ -n "$previous" ]; then
  # Only a release this workflow deployed is restored: its .env carries every value. An older
  # deploy kept its secrets in the shell, and its compose without them would start broken.
  cp -rp .previous/. .
  if docker compose up -d && ready && healthy "$previous"; then
    echo "::error::rolled back to $previous — production runs the previous release"
  else
    echo "::error::the rollback to $previous did not come up healthy either — look now"
  fi
else
  echo "::error::no previous release deployed by this workflow here — nothing to roll back to"
fi
exit 1
"""


def env_line(name, value):
    if "\n" in value or "'" in value:
        raise ValueError(f"{name}: a value with a newline or a single quote cannot go into .env safely")
    return f"{name}='{value}'"


def cmd_bundle(out):
    c = parse()
    errors = lint(c)
    if c is None or errors:
        for e in errors:
            print(f"::error::{e}")
        return 1
    f = facts(c)
    d, service, health, files = f["dir"], f["service"], f["health"], f["files"]
    secrets = json.loads(os.environ.get("SECRETS_JSON") or "{}")
    variables = json.loads(os.environ.get("VARS_JSON") or "{}")
    version = os.environ.get("APP_VERSION", "")
    port = str(variables.get("APP_PORT") or "")
    missing = [] if port.isdigit() else ["APP_PORT (variable)"]
    if not re.match(r"^\d+\.\d+\.\d+", version):
        missing.append("APP_VERSION (from the tag)")
    lines = [f"APP_VERSION='{version}'", f"APP_PORT='{port}'", f"DATA_DIR='{f['data']}'"]
    for name, required in sorted(c["refs"].items()):
        if name in PROVIDED:
            continue
        value = secrets.get(name, variables.get(name))
        if value is None:
            if required:
                missing.append(name)
            continue
        try:
            lines.append(env_line(name, str(value)))
        except ValueError as e:
            print(f"::error::{e}")
            return 1
    if missing:
        print(f"::error::missing in environment prod: {', '.join(missing)}")
        return 1

    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    for rel in files:
        dst = os.path.join(out, rel)
        os.makedirs(os.path.dirname(dst) or out, exist_ok=True)
        shutil.copy2(os.path.join(ROOT, rel), dst)

    def private(name, text):
        fd = os.open(os.path.join(out, name), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)

    private(".env", "\n".join(lines) + "\n")
    private(".ghcr", os.environ.get("GHCR_TOKEN", ""))
    script = REMOTE
    for key, value in {
        "__DIR__": d,
        "__SERVICE__": service,
        "__HEALTH__": health,
        "__VERSION__": version,
        "__PORT__": port,
        "__USER__": os.environ.get("GHCR_USER", ""),
    }.items():
        script = script.replace(key, shlex.quote(str(value)))
    script = script.replace("__FILES__", " ".join(shlex.quote(f) for f in files))
    private(".deploy.sh", script)
    print(f"bundle: {service} → {d}, {len(files)} file(s), {len(lines)} value(s) in .env")
    return 0


def cmd_get(key):
    c = parse()
    if c is None or key not in ("dir", "service", "health", "data"):
        print(f"no {COMPOSE}" if c is None else f"unknown key {key!r}", file=sys.stderr)
        return 2
    value = facts(c)[key]
    if not value:
        print(f"{key}: cannot be derived — run `python scripts/deploy.py lint`", file=sys.stderr)
        return 1
    print(value)
    return 0


def main(argv):
    if not argv or argv[0] == "lint":
        return cmd_lint()
    if argv[0] == "bundle" and len(argv) == 2:
        return cmd_bundle(argv[1])
    if argv[0] == "get" and len(argv) == 2:
        return cmd_get(argv[1])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
