# Multi-stage build for Go WhatsApp bridge
FROM golang:1.25-alpine AS builder

WORKDIR /app

# Install build dependencies for CGO (needed for SQLite) and git for module downloads
RUN apk add --no-cache gcc musl-dev git

# Copy go mod files and source code
COPY go.mod ./
COPY . .

# Download dependencies and update go.sum
RUN go mod download && go mod tidy

# Build the application
RUN CGO_ENABLED=1 GOOS=linux go build -a -installsuffix cgo -o bridge .

# Final stage
FROM alpine:latest

# Install dependencies for SQLite and QR code generation
RUN apk add --no-cache \
    sqlite \
    ca-certificates \
    tzdata

WORKDIR /app

# Copy the binary from builder
COPY --from=builder /app/bridge .

# Create store directory for persistent data
RUN mkdir -p /app/store

# Expose REST API port
EXPOSE 8080

# Run the bridge
CMD ["./bridge"]
