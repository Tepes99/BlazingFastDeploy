# Bootstrap

Bootstrap is an idempotent setup and repair operation for the existing VPS. Preview its exact checks and intended changes first:

```bash
ship bootstrap --dry-run
```

The preview makes a read-only SSH connection. It reads `/etc/os-release`, verifies Ubuntu 26.04 with codename `resolute`, checks `x86_64`, disk space, and listeners on ports 80 and 443. It makes no server changes.

When explicitly ready to change the VPS, run:

```bash
ship bootstrap
```

Bootstrap installs Docker Engine, Buildx, and Compose from Docker's official Ubuntu apt repository using the detected codename. It installs Caddy from Caddy's official repository, creates the `deploy` user, copies root's working `authorized_keys`, adds `deploy` to the Docker group, creates platform directories, installs the remote helpers, enables Docker and Caddy, and validates Caddy.

It does not disable root SSH, disable passwords, edit the firewall, change DNS, reboot, or delete applications and data. It tests a separate `deploy@apps.teemusaha.com` connection before offering to write `~/.config/ship/config.toml`. Existing local configuration is preserved.

If ports 80 or 443 have unexpected listeners, inspect them before continuing. An existing Caddy listener is expected on a repeat run. Docker-group membership grants root-equivalent control of the host; this is an accepted tradeoff for this personal version.

