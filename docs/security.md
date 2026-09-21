# Security

The CLI invokes subprocesses with argument arrays. It strictly validates application names, domains, paths, SSH targets, release IDs, and ports. Remote command arguments are individually POSIX-quoted because OpenSSH passes its remote command through a shell. Large lifecycle operations reside in an installed server-side Python helper rather than interpolated shell scripts.

Applications publish only on `127.0.0.1`; Caddy is the public ingress. Environment files travel separately, use mode `0600`, remain outside releases, and are never printed. State writes and current-release changes are atomic. A per-application lock prevents concurrent deploys. The Caddy helper builds a complete staged configuration, validates it, atomically updates one validated application filename, and reloads Caddy. Its sudo entry is limited to that validating helper.

Membership in the Docker group is effectively root access. The personal `deploy` account receives that power so it can manage containers without broad passwordless sudo. Root login remains enabled and password authentication is not changed, avoiding accidental lockout. Later hardening can restrict SSH source addresses, disable passwords after verifying keys, move deployment behind a private network, and replace Docker-group access with a more isolated service. Make those changes separately and retain a tested recovery path.

`ship remove <app>` preserves data, secrets, and releases. `--delete-data` prints the exact data path and requires an interactive confirmation or `--yes`. The helper independently reconstructs and validates the application-specific path before deletion. No global Docker pruning occurs.

