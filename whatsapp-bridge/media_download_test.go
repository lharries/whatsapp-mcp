package main

import (
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestExtractDirectPathFromURL(t *testing.T) {
	tests := []struct {
		name  string
		input string
		want  string
	}{
		{
			name:  "signed media URL",
			input: "https://mmg.whatsapp.net/v/t62/file.enc?ccb=11-4&oh=test-signature&oe=12345678",
			want:  "/v/t62/file.enc?ccb=11-4&oh=test-signature&oe=12345678",
		},
		{
			name:  "preserve query escaping and order",
			input: "https://media.whatsapp.net/v/file.enc?oh=a%2Fb%2Bc&oe=12345678&token=a+b&token=second",
			want:  "/v/file.enc?oh=a%2Fb%2Bc&oe=12345678&token=a+b&token=second",
		},
		{
			name:  "URL without query",
			input: "https://mmg.whatsapp.net/v/file.enc",
			want:  "/v/file.enc",
		},
		{
			name:  "already a direct path",
			input: "/v/file.enc?oh=test-signature&oe=12345678",
			want:  "/v/file.enc?oh=test-signature&oe=12345678",
		},
		{
			name:  "preserve existing fallback",
			input: "https://example.com/file.enc?oh=test-signature",
			want:  "https://example.com/file.enc?oh=test-signature",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := extractDirectPathFromURL(tt.input); got != tt.want {
				t.Errorf("extractDirectPathFromURL(%q) = %q, want %q", tt.input, got, tt.want)
			}
		})
	}
}

func TestMediaDownloadPreservesCDNAuthorization(t *testing.T) {
	const path = "/v/t62/file.enc"
	const query = "ccb=11-4&oh=test-signature&oe=12345678"
	const payload = "test encrypted media"
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != path || r.URL.RawQuery != query {
			http.Error(w, "missing CDN authorization", http.StatusForbidden)
			return
		}
		_, _ = io.WriteString(w, payload)
	}))
	defer server.Close()

	// The fixture must reject the unsigned path, as the WhatsApp CDN does.
	unsigned, err := server.Client().Get(server.URL + path)
	if err != nil {
		t.Fatal(err)
	}
	_ = unsigned.Body.Close()
	if unsigned.StatusCode != http.StatusForbidden {
		t.Fatalf("unsigned request returned %d, want 403", unsigned.StatusCode)
	}

	// whatsmeow rebuilds the request URL using the bridge's direct path.
	directPath := extractDirectPathFromURL("https://mmg.whatsapp.net" + path + "?" + query)
	resp, err := server.Client().Get(server.URL + directPath)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("signed media download returned %d, want 200", resp.StatusCode)
	}
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatal(err)
	}
	if string(body) != payload {
		t.Fatalf("downloaded body = %q, want %q", body, payload)
	}
}
