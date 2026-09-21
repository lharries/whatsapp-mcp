package main

import "testing"

// Fixtures below are synthetic, but structurally identical to the two real
// URL shapes observed in production traffic (both carry a query string).
const (
	vStyleURL  = "https://mmg.whatsapp.net/v/t62.7117-24/100000000_1000000000000000_1000000000000000000_n.enc?ccb=11-4&oh=01_SyntheticFixtureOhTokenNotARealSignatureAAAA&oe=00000000&_nc_sid=000000&mms3=true"
	o1StyleURL = "https://mmg.whatsapp.net/o1/v/t24/f2/m235/BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB?ccb=9-4&oh=01_SyntheticFixtureOhTokenNotARealSignatureBBBB&oe=00000000&_nc_sid=000000&mms3=true"
)

// This is the test that would have caught the original bug: run it against
// the OLD extractDirectPathFromURL (query-stripped) and it fails, because
// the old function discarded everything after "?".
func TestExtractDirectPathFromURL_PreservesQueryByteForByte(t *testing.T) {
	cases := []struct {
		name string
		url  string
		want string
	}{
		{
			name: "v-style",
			url:  vStyleURL,
			want: "/v/t62.7117-24/100000000_1000000000000000_1000000000000000000_n.enc?ccb=11-4&oh=01_SyntheticFixtureOhTokenNotARealSignatureAAAA&oe=00000000&_nc_sid=000000&mms3=true",
		},
		{
			name: "o1-style",
			url:  o1StyleURL,
			want: "/o1/v/t24/f2/m235/BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB?ccb=9-4&oh=01_SyntheticFixtureOhTokenNotARealSignatureBBBB&oe=00000000&_nc_sid=000000&mms3=true",
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := extractDirectPathFromURL(tc.url)
			if got != tc.want {
				t.Errorf("extractDirectPathFromURL(%q)\n  got:  %q\n  want: %q", tc.url, got, tc.want)
			}
			if got == "" || got[0] != '/' {
				t.Errorf("direct path must start with '/', got %q", got)
			}
		})
	}
}

// Regression guard against the "obvious" alternative fix that is itself
// wrong: u.String(), u.RequestURI(), or u.Query().Encode() can all
// re-escape path segments or reorder/re-encode query parameters, which
// invalidates the CDN's signature just as thoroughly as stripping the
// query outright. The query must survive character-for-character, in its
// original order.
func TestExtractDirectPathFromURL_DoesNotReencodeOrReorderQuery(t *testing.T) {
	url := "https://mmg.whatsapp.net/v/t62.7117-24/foo.enc?ccb=11-4&oh=ZZZ&oe=00000000&_nc_sid=000000&mms3=true"
	want := "/v/t62.7117-24/foo.enc?ccb=11-4&oh=ZZZ&oe=00000000&_nc_sid=000000&mms3=true"
	if got := extractDirectPathFromURL(url); got != want {
		t.Errorf("query was altered:\n  got:  %q\n  want: %q", got, want)
	}
}

// No such row exists in production today (every stored URL carries a
// query), but a missing query must still produce a bare path rather than
// panicking or dropping the leading slash.
func TestExtractDirectPathFromURL_NoQuery(t *testing.T) {
	want := "/v/t62.7117-24/foo.enc"
	if got := extractDirectPathFromURL("https://mmg.whatsapp.net" + want); got != want {
		t.Errorf("extractDirectPathFromURL(no query) = %q, want %q", got, want)
	}
}

// An unparseable URL must fall back to the original input rather than
// panicking -- callers already treat a non-"/"-prefixed direct path as a
// signal something is wrong upstream.
func TestExtractDirectPathFromURL_RejectsUnparseable(t *testing.T) {
	bad := "://not a url at all"
	if got := extractDirectPathFromURL(bad); got != bad {
		t.Errorf("extractDirectPathFromURL(unparseable) = %q, want original input back", got)
	}
}
