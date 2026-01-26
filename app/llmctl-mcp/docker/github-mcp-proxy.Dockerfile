FROM busybox:1.36.1 AS busybox

FROM ghcr.io/github/github-mcp-server:latest

COPY --from=busybox /bin/busybox /bin/busybox
