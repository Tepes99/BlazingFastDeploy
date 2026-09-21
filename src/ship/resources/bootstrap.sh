#!/usr/bin/env bash
set -euo pipefail

deploy_user="${1:-deploy}"
remote_root="${2:-/srv/ship}"
script_dir="$(cd -- "$(dirname -- "$0")" && pwd)"

. /etc/os-release
test "${ID:-}" = ubuntu || { echo "Ubuntu is required" >&2; exit 1; }
test "${VERSION_ID:-}" = 26.04 || { echo "Ubuntu 26.04 is required, found ${VERSION_ID:-unknown}" >&2; exit 1; }
test "${VERSION_CODENAME:-}" = resolute || { echo "expected codename resolute" >&2; exit 1; }
test "$(uname -m)" = x86_64 || { echo "x86_64 is required" >&2; exit 1; }
case "$remote_root" in
    /*) ;;
    *) echo "remote_root must be absolute" >&2; exit 1 ;;
esac
case "$remote_root" in
    *..*|*[!A-Za-z0-9._/-]*) echo "remote_root contains unsafe characters" >&2; exit 1 ;;
esac
available_kb="$(df -Pk / | awk 'NR==2 {print $4}')"
test "$available_kb" -ge 5242880 || { echo "at least 5 GiB free space is required" >&2; exit 1; }

for port in 80 443; do
    listeners="$(ss -H -ltnp "sport = :$port" || true)"
    if test -n "$listeners" && ! printf '%s\n' "$listeners" | grep -q 'users:(("caddy"'; then
        echo "TCP port $port has an unexpected listener:" >&2
        printf '%s\n' "$listeners" >&2
        exit 1
    fi
done

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl gnupg debian-keyring debian-archive-keyring apt-transport-https rsync

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${VERSION_CODENAME}
Components: stable
Architectures: amd64
Signed-By: /etc/apt/keyrings/docker.asc
EOF
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg.tmp
mv /usr/share/keyrings/caddy-stable-archive-keyring.gpg.tmp /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' -o /etc/apt/sources.list.d/caddy-stable.list
apt-get update
apt-get install -y caddy

if ! id "$deploy_user" >/dev/null 2>&1; then
    useradd --create-home --shell /bin/bash "$deploy_user"
fi
install -d -m 0700 -o "$deploy_user" -g "$deploy_user" "/home/$deploy_user/.ssh"
if test -s /root/.ssh/authorized_keys; then
    install -m 0600 -o "$deploy_user" -g "$deploy_user" /root/.ssh/authorized_keys "/home/$deploy_user/.ssh/authorized_keys"
else
    echo "root has no authorized_keys to copy" >&2
    exit 1
fi
usermod -aG docker "$deploy_user"

install -d -m 0750 -o "$deploy_user" -g "$deploy_user" "$remote_root" "$remote_root/apps" "$remote_root/releases" "$remote_root/state" "$remote_root/state/locks" "$remote_root/state/caddy"
install -d -m 0755 -o root -g root /etc/caddy/apps
install -d -m 0755 -o root -g root /etc/ship
printf '{"remote_root":"%s"}\n' "$remote_root" > /etc/ship/config.json
chmod 0644 /etc/ship/config.json
test -f "$remote_root/state/apps.json" || printf '{"version":1,"apps":{}}\n' > "$remote_root/state/apps.json"
chown "$deploy_user:$deploy_user" "$remote_root/state/apps.json"
chmod 0600 "$remote_root/state/apps.json"

if ! grep -Fq 'import /etc/caddy/apps/*.caddy' /etc/caddy/Caddyfile; then
    printf '\n# Managed application routes\nimport /etc/caddy/apps/*.caddy\n' >> /etc/caddy/Caddyfile
fi
install -m 0755 -o root -g root "$script_dir/ship_remote.py" /usr/local/bin/ship-remote
install -m 0755 -o root -g root "$script_dir/ship_caddy.py" /usr/local/sbin/ship-caddy
cat > /etc/sudoers.d/ship-caddy <<EOF
$deploy_user ALL=(root) NOPASSWD: /usr/local/sbin/ship-caddy *
EOF
chmod 0440 /etc/sudoers.d/ship-caddy
visudo -cf /etc/sudoers.d/ship-caddy
caddy validate --config /etc/caddy/Caddyfile
systemctl enable --now docker caddy
echo "ship bootstrap complete"
