package main

import (
	"path/filepath"
	"strings"
	"testing"
)

func TestMediaLocalNameUniquePerMessage(t *testing.T) {
	// History sync names media after the receive second, so many messages
	// in one chat share a filename.
	shared := "image_20261106_113929.jpg"
	a := mediaLocalName("3EB087CEB87C495FE84709", shared)
	b := mediaLocalName("3EB0CC41A252D7F44CD5B7", shared)
	if a == b {
		t.Fatalf("two messages with the same stored filename got the same local name %q", a)
	}
	if !strings.HasSuffix(a, ".jpg") {
		t.Fatalf("local name %q lost the file extension", a)
	}
}

func TestMediaLocalNameStableForSameMessage(t *testing.T) {
	first := mediaLocalName("3EB087CEB87C495FE84709", "image_20261106_113929.jpg")
	second := mediaLocalName("3EB087CEB87C495FE84709", "image_20261106_113929.jpg")
	if first != second {
		t.Fatalf("same message produced different names: %q vs %q", first, second)
	}
}

func TestMediaLocalNameStaysInChatDir(t *testing.T) {
	for _, name := range []string{`../../evil.exe`, `..\..\evil.exe`, `sub/dir/report.pdf`} {
		got := mediaLocalName("3EB0ABC", name)
		if got != filepath.Base(got) || strings.ContainsAny(got, `/\`) {
			t.Fatalf("document name %q escaped the chat folder as %q", name, got)
		}
	}
}
