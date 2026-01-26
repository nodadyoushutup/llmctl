FROM ghcr.io/github/github-mcp-server:latest AS github_mcp

FROM ghcr.io/sparfenyuk/mcp-proxy:latest

COPY --from=github_mcp /server/github-mcp-server /usr/local/bin/github-mcp-server

ENTRYPOINT ["catatonit", "--", "mcp-proxy"]
