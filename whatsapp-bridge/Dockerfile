# Build stage
FROM golang:1.25-alpine AS builder

# Install build dependencies
RUN apk add --no-cache gcc musl-dev sqlite-dev

WORKDIR /app

# Copy go mod files
COPY go.mod go.sum ./
RUN go mod download

# Copy source code
COPY . .

# Build with CGO enabled for SQLite
RUN CGO_ENABLED=1 go build -o whatsapp-bridge .

# Runtime stage
FROM alpine:3.19

# Install runtime dependencies
RUN apk add --no-cache ca-certificates sqlite-libs

WORKDIR /app

# Copy binary from builder
COPY --from=builder /app/whatsapp-bridge .

# Create store directory for session data
RUN mkdir -p /app/store

# Environment variables
ENV HTTP_PORT=8080
ENV QR_MODE=http

# Expose HTTP port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD wget -q --spider http://localhost:${HTTP_PORT}/api/auth/status || exit 1

# Run the application
CMD ["./whatsapp-bridge"]
