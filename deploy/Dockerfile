# Build context is the repository root:  docker build -f deploy/Dockerfile .
FROM golang:1.26-bookworm AS build
WORKDIR /src
COPY whatsapp-bridge/go.mod whatsapp-bridge/go.sum ./
RUN go mod download
COPY whatsapp-bridge/ ./
RUN CGO_ENABLED=1 go build -o /out/wa-bridge .

FROM debian:bookworm-slim
RUN useradd --system --home /data --shell /usr/sbin/nologin wa \
 && mkdir -p /data && chown wa:wa /data
COPY --from=build /out/wa-bridge /usr/local/bin/wa-bridge
USER wa
ENV WA_DB_DIR=/data WA_PORT=8080 WA_ACCOUNT=main
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["/bin/sh", "-c", "timeout 2 bash -c '</dev/tcp/127.0.0.1/8080' || exit 1"]
# Exec form so SIGTERM reaches the process and it can disconnect cleanly.
CMD ["wa-bridge"]
