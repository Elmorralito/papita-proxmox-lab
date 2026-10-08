Place k8s-bearer.token here on the CT only. Never commit the token.

Prometheus mounts this directory at /etc/prometheus/secrets (see docker-compose.yml).
The scrape jobs read /etc/prometheus/secrets/k8s-bearer.token (prometheus-external SA on the k8s cluster).
