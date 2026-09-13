package main

import (
	"testing"

	waProto "go.mau.fi/whatsmeow/binary/proto"
)

// ptr avoids pulling google.golang.org/protobuf in as a direct dependency just
// to build test fixtures.
func ptr[T any](v T) *T { return &v }

// Captions were a silent hole: a message was stored with an empty content
// column, which looks exactly like an image sent without a single word. This
// test exists so that difference cannot quietly disappear again.
func TestExtractTextContent(t *testing.T) {
	cases := []struct {
		name string
		msg  *waProto.Message
		want string
	}{
		{"nil", nil, ""},
		{
			"conversation",
			&waProto.Message{Conversation: ptr("hello")},
			"hello",
		},
		{
			"extended text",
			&waProto.Message{ExtendedTextMessage: &waProto.ExtendedTextMessage{Text: ptr("hello")}},
			"hello",
		},
		{
			"image with caption",
			&waProto.Message{ImageMessage: &waProto.ImageMessage{Caption: ptr("look at this")}},
			"look at this",
		},
		{
			"image without caption",
			&waProto.Message{ImageMessage: &waProto.ImageMessage{}},
			"",
		},
		{
			"multiline caption is preserved",
			&waProto.Message{ImageMessage: &waProto.ImageMessage{Caption: ptr("first\nsecond\n\nfourth")}},
			"first\nsecond\n\nfourth",
		},
		{
			"video with caption",
			&waProto.Message{VideoMessage: &waProto.VideoMessage{Caption: ptr("clip")}},
			"clip",
		},
		{
			"document with caption",
			&waProto.Message{DocumentMessage: &waProto.DocumentMessage{Caption: ptr("the contract")}},
			"the contract",
		},
		{
			// How a captioned document actually arrives over history sync.
			"document-with-caption envelope",
			&waProto.Message{DocumentWithCaptionMessage: &waProto.FutureProofMessage{
				Message: &waProto.Message{DocumentMessage: &waProto.DocumentMessage{
					Caption: ptr("the contract"),
				}},
			}},
			"the contract",
		},
		{
			"nested envelopes: ephemeral around view-once",
			&waProto.Message{EphemeralMessage: &waProto.FutureProofMessage{
				Message: &waProto.Message{ViewOnceMessageV2: &waProto.FutureProofMessage{
					Message: &waProto.Message{ImageMessage: &waProto.ImageMessage{
						Caption: ptr("disappearing"),
					}},
				}},
			}},
			"disappearing",
		},
		{
			// Audio has no caption field in the protocol; nothing to invent.
			"audio",
			&waProto.Message{AudioMessage: &waProto.AudioMessage{}},
			"",
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := extractTextContent(tc.msg); got != tc.want {
				t.Errorf("extractTextContent() = %q, want %q", got, tc.want)
			}
		})
	}
}

// An enveloped image must keep its attachment, not just its caption.
func TestExtractMediaInfoUnwraps(t *testing.T) {
	msg := &waProto.Message{ViewOnceMessageV2: &waProto.FutureProofMessage{
		Message: &waProto.Message{ImageMessage: &waProto.ImageMessage{
			Caption:    ptr("x"),
			FileLength: ptr(uint64(213903)),
		}},
	}}

	mediaType, _, _, _, _, _, fileLength := extractMediaInfo(msg)
	if mediaType != "image" {
		t.Errorf("mediaType = %q, want %q", mediaType, "image")
	}
	if fileLength != 213903 {
		t.Errorf("fileLength = %d, want 213903", fileLength)
	}
}
