package main

import (
	"errors"
	"testing"

	"go.mau.fi/whatsmeow/types"
)

// fakeResolver simulates the live WhatsApp directory so the resolution logic can
// be exercised without a connection.
type fakeResolver struct {
	pnForLID map[string]string    // LID digits -> phone digits
	onWhats  map[string]types.JID // phone digits -> current canonical JID
	err      error                // when set, IsOnWhatsApp fails
}

func (f fakeResolver) PNForLID(lidUser string) (string, bool) {
	pn, ok := f.pnForLID[lidUser]
	return pn, ok
}

func (f fakeResolver) IsOnWhatsApp(user string) (types.JID, bool, error) {
	if f.err != nil {
		return types.JID{}, false, f.err
	}
	jid, ok := f.onWhats[user]
	if !ok {
		return types.JID{}, false, nil
	}
	return jid, true, nil
}

func TestDigitsOnly(t *testing.T) {
	cases := map[string]string{
		"+264 81 772 1286":   "264817721286",
		"264-817721286":      "264817721286",
		"(264) 817721286":    "264817721286",
		"264817721286":       "264817721286",
		"+264 (81) 772-1286": "264817721286",
		"":                   "",
		"no digits":          "",
	}
	for in, want := range cases {
		if got := digitsOnly(in); got != want {
			t.Errorf("digitsOnly(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestResolveSendTarget(t *testing.T) {
	const pn = "264817721286"
	fresh := types.JID{User: "212558418043069", Server: types.HiddenUserServer}
	stale := types.JID{User: "41635530444913", Server: types.HiddenUserServer}
	group := types.JID{User: "120363000000000000", Server: "g.us"}

	base := fakeResolver{
		pnForLID: map[string]string{stale.User: pn},
		onWhats:  map[string]types.JID{pn: fresh},
	}

	tests := []struct {
		name      string
		resolver  sendResolver
		recipient string
		want      types.JID
		wantErr   bool
	}{
		{
			name:      "bare phone number resolves to current canonical LID",
			resolver:  base,
			recipient: pn,
			want:      fresh,
		},
		{
			name:      "formatted phone number is normalised",
			resolver:  base,
			recipient: "+264 81 772 1286",
			want:      fresh,
		},
		{
			name:      "stale LID is remapped through the phone number to the current account",
			resolver:  base,
			recipient: stale.String(),
			want:      fresh,
		},
		{
			name: "current LID remaps to the same current account",
			resolver: fakeResolver{
				pnForLID: map[string]string{fresh.User: pn},
				onWhats:  map[string]types.JID{pn: fresh},
			},
			recipient: fresh.String(),
			want:      fresh,
		},
		{
			name: "unknown LID falls back to resolving the LID digits",
			resolver: fakeResolver{
				onWhats: map[string]types.JID{stale.User: fresh},
			},
			recipient: stale.String(),
			want:      fresh,
		},
		{
			name:      "phone JID is resolved to the current canonical JID",
			resolver:  base,
			recipient: pn + "@" + types.DefaultUserServer,
			want:      fresh,
		},
		{
			name:      "group JID is passed through untouched",
			resolver:  base,
			recipient: group.String(),
			want:      group,
		},
		{
			name:      "number not on WhatsApp is an error",
			resolver:  base,
			recipient: "264999999999",
			wantErr:   true,
		},
		{
			name:      "resolver failure falls back to the phone JID (best effort)",
			resolver:  fakeResolver{err: errors.New("network down")},
			recipient: pn,
			want:      types.JID{User: pn, Server: types.DefaultUserServer},
		},
		{
			name:      "empty recipient is an error",
			resolver:  base,
			recipient: "   ",
			wantErr:   true,
		},
		{
			name:      "unparseable phone number is an error",
			resolver:  base,
			recipient: "not-a-number",
			wantErr:   true,
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			got, err := resolveSendTarget(tc.resolver, tc.recipient)
			if tc.wantErr {
				if err == nil {
					t.Fatalf("expected error, got %v", got)
				}
				return
			}
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if got.User != tc.want.User || got.Server != tc.want.Server {
				t.Fatalf("resolveSendTarget(%q) = %s, want %s", tc.recipient, got.String(), tc.want.String())
			}
		})
	}
}
