package main

import "testing"

func TestExtractDirectPathKeepsSignature(t *testing.T) {
	url := "https://mmg.whatsapp.net/v/t62.7118-24/789_1463_173_n.enc?ccb=11-4&oh=SIG&oe=6ABA5D50&_nc_sid=5e03e0&mms3=true"
	want := "/v/t62.7118-24/789_1463_173_n.enc?ccb=11-4&oh=SIG&oe=6ABA5D50&_nc_sid=5e03e0"
	if got := extractDirectPathFromURL(url); got != want {
		t.Fatalf("got %q want %q", got, want)
	}
	if got := extractDirectPathFromURL("garbage"); got != "garbage" {
		t.Fatalf("fallback broken: %q", got)
	}
}
