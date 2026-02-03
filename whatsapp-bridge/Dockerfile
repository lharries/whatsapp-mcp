FROM golang:1.24-bookworm AS builder

WORKDIR /app

COPY go.mod go.sum ./
RUN go mod download

COPY . .

# CGO is required for go-sqlite3
RUN CGO_ENABLED=1 go build -o whatsapp-bridge .

FROM debian:bookworm-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /app/whatsapp-bridge .

RUN mkdir -p store

EXPOSE 8080

CMD ["./whatsapp-bridge"]
