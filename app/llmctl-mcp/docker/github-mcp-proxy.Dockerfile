FROM alpine:3.20 AS busybox
RUN apk add --no-cache busybox-static

FROM ghcr.io/github/github-mcp-server:latest

COPY --from=busybox /bin/busybox.static /bin/busybox
