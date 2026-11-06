package main

import (
	"testing"

	waProto "go.mau.fi/whatsmeow/binary/proto"
	"go.mau.fi/whatsmeow/types"
	"google.golang.org/protobuf/proto"
)

func TestHistorySender(t *testing.T) {
	group := types.NewJID("120363405921788106", types.GroupServer)
	direct := types.NewJID("6282138711691", types.DefaultUserServer)

	cases := []struct {
		name string
		chat types.JID
		msg  *waProto.WebMessageInfo
		want string
	}{
		{
			// History sync puts the group author here and leaves Key.Participant empty.
			name: "group author in WebMessageInfo.Participant",
			chat: group,
			msg: &waProto.WebMessageInfo{
				Key:         &waProto.MessageKey{FromMe: proto.Bool(false)},
				Participant: proto.String("104784384290844@lid"),
			},
			want: "104784384290844",
		},
		{
			name: "group author only in Key.Participant",
			chat: group,
			msg: &waProto.WebMessageInfo{
				Key: &waProto.MessageKey{FromMe: proto.Bool(false), Participant: proto.String("6281234567890:12@s.whatsapp.net")},
			},
			want: "6281234567890",
		},
		{
			name: "group message without any author falls back to the chat",
			chat: group,
			msg:  &waProto.WebMessageInfo{Key: &waProto.MessageKey{FromMe: proto.Bool(false)}},
			want: "120363405921788106",
		},
		{
			name: "own message",
			chat: group,
			msg: &waProto.WebMessageInfo{
				Key:         &waProto.MessageKey{FromMe: proto.Bool(true)},
				Participant: proto.String("104784384290844@lid"),
			},
			want: "6282138554318",
		},
		{
			name: "direct chat uses the chat itself",
			chat: direct,
			msg:  &waProto.WebMessageInfo{Key: &waProto.MessageKey{FromMe: proto.Bool(false)}},
			want: "6282138711691",
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := historySender(tc.chat, tc.msg, "6282138554318"); got != tc.want {
				t.Fatalf("historySender() = %q, want %q", got, tc.want)
			}
		})
	}
}
