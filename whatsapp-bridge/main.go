package main

import (
	"context"
	"os"
	"os/signal"
	"strconv"
	"syscall"

	_ "github.com/mattn/go-sqlite3"
	waLog "go.mau.fi/whatsmeow/util/log"
)

func main() {
	logger := waLog.Stdout("Bridge", "INFO", true)

	config, err := LoadConfig()
	if err != nil {
		logger.Errorf("Failed to load config: %v", err)
		os.Exit(1)
	}

	logger.Infof("Starting WhatsApp Bridge in multi-user mode")
	logger.Infof("Django URL: %s", config.DjangoURL)
	logger.Infof("Poll interval: %v", config.PollInterval)
	logger.Infof("Max users: %d", config.MaxUsers)

	bridge := NewBridge(config, logger)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	go func() {
		if err := bridge.Start(ctx); err != nil {
			logger.Errorf("Bridge error: %v", err)
		}
	}()

	logger.Infof("Bridge started, polling Django every %v", config.PollInterval)

	addr := ":" + strconv.Itoa(config.Port)
	logger.Infof("Starting HTTP server on %s", addr)
	if err := bridge.ServeHTTP(addr); err != nil {
		logger.Errorf("HTTP server error: %v", err)
	}

	logger.Infof("WhatsApp Bridge is running. Press Ctrl+C to stop.")

	exitChan := make(chan os.Signal, 1)
	signal.Notify(exitChan, syscall.SIGINT, syscall.SIGTERM)
	<-exitChan

	logger.Infof("Shutting down...")
	bridge.Stop()
	cancel()
	logger.Infof("Bridge stopped.")
}