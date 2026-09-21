# DNS

You already own `teemusaha.com`; no additional domain or authoritative DNS zone is needed. Keep the existing AWS Route 53 setup and nameservers because other AWS-hosted infrastructure depends on them.

The Route 53 hosted zone must contain both records:

```text
apps.teemusaha.com A 2.29.47.65
*.apps.teemusaha.com A 2.29.47.65
```

Keep the existing apex-of-platform record. Add the wildcard if it is missing. The wildcard makes names such as `medicine.apps.teemusaha.com` resolve without creating a record for each application. `ship check` queries a random-looking application hostname and prints the exact missing record. It needs no AWS credentials and never modifies Route 53.

Once DNS resolves and TCP ports 80 and 443 reach Caddy, Caddy obtains and renews public HTTPS certificates automatically.

