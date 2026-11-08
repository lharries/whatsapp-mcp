package main

import (
	"os"
	"testing"

	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/store"
	"go.mau.fi/whatsmeow/types"
)

func TestRecipientAllowed(t *testing.T) {
	ownDevice := types.NewADJID("15550001111", 0, 3)
	client := &whatsmeow.Client{Store: &store.Device{ID: &ownDevice}}
	own := types.NewJID("15550001111", types.DefaultUserServer)
	friend := types.NewJID("15550002222", types.DefaultUserServer)
	group := types.NewJID("15550002222", types.GroupServer)

	cases := []struct {
		name string
		env  *string
		to   types.JID
		want bool
	}{
		{"unset allows anyone", nil, friend, true},
		{"self allows own chat", ptr("self"), own, true},
		{"self rejects others", ptr("self"), friend, false},
		{"phone number", ptr("self, 15550002222"), friend, true},
		{"full JID", ptr("15550002222@s.whatsapp.net"), friend, true},
		{"bare number is not a group", ptr("15550002222"), group, false},
		{"empty denies all", ptr(""), own, false},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			t.Setenv("WHATSAPP_ALLOWED_RECIPIENTS", "")
			if c.env == nil {
				os.Unsetenv("WHATSAPP_ALLOWED_RECIPIENTS")
			} else {
				os.Setenv("WHATSAPP_ALLOWED_RECIPIENTS", *c.env)
			}
			if got := recipientAllowed(client, c.to); got != c.want {
				t.Errorf("recipientAllowed(%s) = %v, want %v", c.to, got, c.want)
			}
		})
	}
}

func ptr(s string) *string { return &s }
