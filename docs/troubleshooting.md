# Troubleshooting

Run `ship check` first. It separates passing checks, warnings, and blocking failures and prints a correction for each problem. `ship check --json` is suitable for another local tool.

If SSH fails, verify `ssh deploy@apps.teemusaha.com` and your normal SSH agent/config. If bootstrap SSH fails, verify `ssh root@apps.teemusaha.com`. No keys or passwords belong in ship's config.

If HTTPS fails, confirm both Route 53 records in [dns.md](dns.md), allow inbound TCP 80 and 443 in the Hetzner firewall, and inspect `ship status <app>` and `ship logs <app>`. Caddy certificate issuance needs public DNS and both ports.

If candidate health fails, the current production container and Caddy route remain untouched. Read the included build/container output and ensure the image listens on `0.0.0.0:<container_port>` internally and serves the configured health path. If new production health fails, ship removes it and attempts to restore and verify the prior image against the same persistent data.

If a lock remains after a killed SSH session, inspect `/srv/ship/state/locks/<app>.lock` on the server. Confirm that no deployment is running before removing that one exact directory manually.

DuckDB schema changes can make image rollback incompatible. Restore a separate data backup when code rollback alone cannot recover.

