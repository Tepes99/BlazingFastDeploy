# Current environment

`ship` is configured for this existing environment:

| Item | Value |
|---|---|
| Provider | Hetzner Cloud |
| Bootstrap SSH | `root@apps.teemusaha.com` |
| Deployment SSH | `deploy@apps.teemusaha.com` |
| Public IPv4 | `2.29.47.65` |
| Base domain | `apps.teemusaha.com` |
| Server architecture | `x86_64` |
| OS | Ubuntu 26.04.1 LTS (Resolute) |
| Root disk | 75 GB, approximately 71 GB free at project start |
| Remote root | `/srv/ship` |
| Intended firewall ports | TCP 22, 80, 443 |

The VPS and domain already exist. The tool must not create another server, purchase a domain, change Route 53, or change the Hetzner firewall.

