package main

import (
	"os"
	"regexp"
	"time"
)

type Config struct {
	DjangoURL        string
	JWTSecret        string
	ServiceKey       string
	PollInterval     time.Duration
	MaxUsers         int
	LogLevel         string
	Port             int
	StorePath        string
}

func LoadConfig() (*Config, error) {
	djangoURL := os.Getenv("DJANGO_API_URL")
	if djangoURL == "" {
		djangoURL = "http://django:8000"
	}

	jwtSecret := os.Getenv("JWT_SECRET")
	if jwtSecret == "" {
		panic("JWT_SECRET is required")
	}

	serviceKey := os.Getenv("SERVICE_KEY")
	if serviceKey == "" {
		panic("SERVICE_KEY is required")
	}

	pollInterval := 60 * time.Second
	if val := os.Getenv("BRIDGE_POLL_INTERVAL"); val != "" {
		if parsed, err := time.ParseDuration(val + "s"); err == nil {
			pollInterval = parsed
		}
	}

	maxUsers := 5
	if val := os.Getenv("MAX_CONCURRENT_USERS"); val != "" {
		if parsed := parseIntEnv(val); parsed > 0 {
			maxUsers = parsed
		}
	}

	logLevel := os.Getenv("LOG_LEVEL")
	if logLevel == "" {
		logLevel = "INFO"
	}

	port := 8080
	if val := os.Getenv("PORT"); val != "" {
		if parsed := parseIntEnv(val); parsed > 0 {
			port = parsed
		}
	}

	storePath := os.Getenv("STORE_PATH")
	if storePath == "" {
		storePath = "store"
	}

	return &Config{
		DjangoURL:    djangoURL,
		JWTSecret:    jwtSecret,
		ServiceKey:   serviceKey,
		PollInterval: pollInterval,
		MaxUsers:     maxUsers,
		LogLevel:     logLevel,
		Port:         port,
		StorePath:    storePath,
	}, nil
}

func parseIntEnv(val string) int {
	var result int
	for _, c := range val {
		if c >= '0' && c <= '9' {
			result = result*10 + int(c-'0')
		}
	}
	return result
}

var userIDRegex = regexp.MustCompile(`^[a-zA-Z0-9\-_]{1,64}$`)

func ValidateUserID(userID string) error {
	if !userIDRegex.MatchString(userID) {
		return &ValidationError{Field: "user_id", Message: "must match pattern ^[a-zA-Z0-9\\-_]{1,64}$"}
	}
	return nil
}

type ValidationError struct {
	Field   string
	Message string
}

func (e *ValidationError) Error() string {
	return e.Field + " " + e.Message
}