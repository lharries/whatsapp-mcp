# Build stage
FROM golang:1.24-alpine AS builder

# Install build dependencies for CGO + SQLite
RUN apk add --no-cache gcc musl-dev sqlite-dev

WORKDIR /app

# Copy dependency files first for better caching
COPY go.mod go.sum ./
RUN go mod download

# Copy source code
COPY . .

# Build with CGO enabled (required for go-sqlite3)
RUN CGO_ENABLED=1 go build -o bridge main.go

# Runtime stage
FROM alpine:3.21

# Install runtime dependencies
RUN apk add --no-cache sqlite-libs ca-certificates

WORKDIR /app

# Copy the binary from the build stage
COPY --from=builder /app/bridge .

# Create the store directory for SQLite databases
RUN mkdir -p /app/store

# Expose the default port (Railway overrides via $PORT)
EXPOSE 8080

CMD ["./bridge"]
