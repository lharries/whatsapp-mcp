package main

import (
	"bytes"
	"crypto/tls"
	"crypto/x509"
	"encoding/pem"
	"io"
	"log"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func localTLSIdentity(t *testing.T) (string, tls.Certificate, *x509.Certificate, []byte) {
	t.Helper()
	directory := t.TempDir()
	if err := initializeLocalTLS(directory); err != nil {
		t.Fatal(err)
	}
	certPath, keyPath := filepath.Join(directory, "bridge-cert.pem"), filepath.Join(directory, "bridge-key.pem")
	pair, err := tls.LoadX509KeyPair(certPath, keyPath)
	if err != nil {
		t.Fatalf("certificate and key do not match: %v", err)
	}
	cert, err := x509.ParseCertificate(pair.Certificate[0])
	if err != nil {
		t.Fatal(err)
	}
	certPEM, err := os.ReadFile(certPath)
	if err != nil {
		t.Fatal(err)
	}
	return directory, pair, cert, certPEM
}

func TestLocalTLSGeneratesValidLoopbackIdentity(t *testing.T) {
	directory, _, cert, certPEM := localTLSIdentity(t)
	if len(cert.IPAddresses) != 1 || !cert.IPAddresses[0].Equal(net.ParseIP("127.0.0.1")) || len(cert.DNSNames) != 0 {
		t.Fatalf("unexpected SANs: IP=%v DNS=%v", cert.IPAddresses, cert.DNSNames)
	}
	if cert.SerialNumber.Sign() <= 0 || !cert.NotBefore.Before(time.Now()) || !cert.NotAfter.After(time.Now().AddDate(9, 0, 0)) {
		t.Fatalf("invalid identity serial or validity interval: serial=%v before=%v after=%v", cert.SerialNumber, cert.NotBefore, cert.NotAfter)
	}
	if err := cert.CheckSignature(cert.SignatureAlgorithm, cert.RawTBSCertificate, cert.Signature); err != nil {
		t.Fatalf("certificate is not validly self-signed: %v", err)
	}
	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(certPEM) {
		t.Fatal("generated certificate cannot be loaded as the private trust anchor")
	}
	opts := x509.VerifyOptions{Roots: pool, DNSName: "127.0.0.1", KeyUsages: []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth}}
	if _, err := cert.Verify(opts); err != nil {
		t.Fatalf("correct identity is not trusted: %v", err)
	}
	for _, host := range []string{"localhost", "127.0.0.2", "example.com"} {
		opts.DNSName = host
		if _, err := cert.Verify(opts); err == nil {
			t.Fatalf("certificate incorrectly authenticates %q", host)
		}
	}
	opts.DNSName = "127.0.0.1"
	opts.CurrentTime = cert.NotAfter.Add(time.Second)
	if _, err := cert.Verify(opts); err == nil {
		t.Fatal("expired certificate was accepted")
	}
	opts.CurrentTime = cert.NotBefore.Add(-time.Second)
	if _, err := cert.Verify(opts); err == nil {
		t.Fatal("not-yet-valid certificate was accepted")
	}
	keyPEM, err := os.ReadFile(filepath.Join(directory, "bridge-key.pem"))
	if err != nil {
		t.Fatal(err)
	}
	block, rest := pem.Decode(keyPEM)
	if block == nil || block.Type != "PRIVATE KEY" || len(bytes.TrimSpace(rest)) != 0 {
		t.Fatal("key is not a single PKCS8 private-key PEM block")
	}
	if _, err := x509.ParsePKCS8PrivateKey(block.Bytes); err != nil {
		t.Fatal(err)
	}
	for _, filename := range []string{"bridge-cert.pem", "bridge-key.pem"} {
		info, err := os.Stat(filepath.Join(directory, filename))
		if err != nil || !info.Mode().IsRegular() {
			t.Fatalf("identity file is not regular: %s, %v", filename, err)
		}
		if runtime.GOOS != "windows" && info.Mode().Perm() != 0600 {
			t.Fatalf("%s permissions=%o, want 0600", filename, info.Mode().Perm())
		}
	}
	if runtime.GOOS == "windows" {
		t.Log("Unix permission bits are not Windows ACL verification; identity files are regular and private-key parsing/key match passed")
	}
}

func TestLocalTLSReinitializationPreservesIdentity(t *testing.T) {
	directory, _, _, beforeCert := localTLSIdentity(t)
	keyPath := filepath.Join(directory, "bridge-key.pem")
	beforeKey, err := os.ReadFile(keyPath)
	if err != nil {
		t.Fatal(err)
	}
	if err := initializeLocalTLS(directory); err != nil {
		t.Fatal(err)
	}
	afterCert, err := os.ReadFile(filepath.Join(directory, "bridge-cert.pem"))
	if err != nil {
		t.Fatal(err)
	}
	afterKey, err := os.ReadFile(keyPath)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(beforeCert, afterCert) || !bytes.Equal(beforeKey, afterKey) {
		t.Fatal("reinitialization silently rotated the TLS identity")
	}
}

func TestLocalTLSMissingKeyFailsWithoutReplacingCertificate(t *testing.T) {
	directory, _, _, beforeCert := localTLSIdentity(t)
	keyPath := filepath.Join(directory, "bridge-key.pem")
	if err := os.Remove(keyPath); err != nil {
		t.Fatal(err)
	}
	if err := initializeLocalTLS(directory); err == nil {
		t.Fatal("accepted existing certificate with missing private key")
	}
	afterCert, err := os.ReadFile(filepath.Join(directory, "bridge-cert.pem"))
	if err != nil || !bytes.Equal(beforeCert, afterCert) {
		t.Fatalf("certificate changed after failure: %v", err)
	}
	if _, err := os.Stat(keyPath); !os.IsNotExist(err) {
		t.Fatalf("unexpected replacement key: %v", err)
	}
}

func TestLocalTLSServerRejectsAbsentOrMismatchedIdentity(t *testing.T) {
	firstDir, _, _, _ := localTLSIdentity(t)
	secondDir, _, _, _ := localTLSIdentity(t)
	for _, tc := range []struct{ name, cert, key string }{
		{"absent", "", ""},
		{"missing-key", filepath.Join(firstDir, "bridge-cert.pem"), filepath.Join(firstDir, "missing-key.pem")},
		{"mismatched-key", filepath.Join(firstDir, "bridge-cert.pem"), filepath.Join(secondDir, "bridge-key.pem")},
	} {
		t.Run(tc.name, func(t *testing.T) {
			t.Setenv("WHATSAPP_TLS_CERT", tc.cert)
			t.Setenv("WHATSAPP_TLS_KEY", tc.key)
			server, err := startRESTServer(nil, nil, 0, strings.Repeat("a", 32))
			if server != nil {
				server.Close()
			}
			if err == nil || server != nil {
				t.Fatalf("started without a valid TLS identity: server=%v err=%v", server, err)
			}
		})
	}
}

type tlsWireCapture struct {
	sync.Mutex
	data []byte
}

type tlsCaptureConn struct {
	net.Conn
	capture *tlsWireCapture
}

func (c *tlsCaptureConn) Read(buffer []byte) (int, error) {
	n, err := c.Conn.Read(buffer)
	c.capture.Lock()
	c.capture.data = append(c.capture.data, buffer[:n]...)
	c.capture.Unlock()
	return n, err
}

type tlsCaptureListener struct {
	net.Listener
	capture *tlsWireCapture
}

func (l *tlsCaptureListener) Accept() (net.Conn, error) {
	conn, err := l.Listener.Accept()
	if err != nil {
		return nil, err
	}
	return &tlsCaptureConn{Conn: conn, capture: l.capture}, nil
}

func tlsTestClient(t *testing.T, certPEM []byte) *http.Client {
	t.Helper()
	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(certPEM) {
		t.Fatal("cannot load trust anchor")
	}
	transport := &http.Transport{TLSClientConfig: &tls.Config{RootCAs: pool, MinVersion: tls.VersionTLS12}}
	t.Cleanup(transport.CloseIdleConnections)
	return &http.Client{Transport: transport, Timeout: 3 * time.Second}
}

func TestLocalTLSCorrectCertificateAuthenticatesBeforeRequest(t *testing.T) {
	_, pair, _, certPEM := localTLSIdentity(t)
	const marker = "Bearer synthetic-local-tls-test-credential"
	var calls atomic.Int32
	server := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		if r.TLS == nil || r.Header.Get("Authorization") != marker {
			t.Error("request lost authenticated TLS or supplied credentials")
		}
		w.WriteHeader(http.StatusNoContent)
	}))
	server.TLS = &tls.Config{Certificates: []tls.Certificate{pair}, MinVersion: tls.VersionTLS12}
	server.StartTLS()
	t.Cleanup(server.Close)
	req, err := http.NewRequest(http.MethodGet, server.URL+"/api/status", nil)
	if err != nil {
		t.Fatal(err)
	}
	req.Header.Set("Authorization", marker)
	response, err := tlsTestClient(t, certPEM).Do(req)
	if err != nil {
		t.Fatal(err)
	}
	response.Body.Close()
	if response.StatusCode != http.StatusNoContent || calls.Load() != 1 {
		t.Fatalf("status=%d calls=%d", response.StatusCode, calls.Load())
	}
}

func TestLocalTLSWrongCertificateOrPlainHTTPReceivesNoCredentials(t *testing.T) {
	_, _, _, trustedPEM := localTLSIdentity(t)
	_, wrongPair, _, _ := localTLSIdentity(t)
	const marker = "synthetic-credential-must-never-reach-untrusted-server"
	for _, mode := range []string{"wrong-certificate", "plain-http"} {
		t.Run(mode, func(t *testing.T) {
			var calls atomic.Int32
			capture := &tlsWireCapture{}
			server := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				calls.Add(1)
				w.WriteHeader(http.StatusOK)
			}))
			server.Listener = &tlsCaptureListener{Listener: server.Listener, capture: capture}
			server.Config.ErrorLog = log.New(io.Discard, "", 0)
			if mode == "wrong-certificate" {
				server.TLS = &tls.Config{Certificates: []tls.Certificate{wrongPair}, MinVersion: tls.VersionTLS12}
				server.StartTLS()
			} else {
				server.Start()
			}
			t.Cleanup(server.Close)
			endpoint := "https://" + strings.TrimPrefix(strings.TrimPrefix(server.URL, "https://"), "http://") + "/api/send"
			req, err := http.NewRequest(http.MethodPost, endpoint, strings.NewReader(`{"recipient":"synthetic","message":"`+marker+`"}`))
			if err != nil {
				t.Fatal(err)
			}
			req.Header.Set("Authorization", "Bearer "+marker)
			req.Header.Set("Content-Type", "application/json")
			response, err := tlsTestClient(t, trustedPEM).Do(req)
			if response != nil {
				response.Body.Close()
			}
			if err == nil {
				t.Fatal("untrusted or non-TLS listener was accepted")
			}
			server.Close()
			if calls.Load() != 0 {
				t.Fatalf("HTTP handler received %d requests before successful server authentication", calls.Load())
			}
			capture.Lock()
			wire := append([]byte(nil), capture.data...)
			capture.Unlock()
			if len(wire) == 0 || wire[0] != 0x16 {
				t.Fatalf("expected TLS handshake first, got %d bytes", len(wire))
			}
			for _, forbidden := range [][]byte{[]byte(marker), []byte("Authorization:"), []byte("POST /api/send")} {
				if bytes.Contains(wire, forbidden) {
					t.Fatalf("HTTP credentials or payload sent before TLS trust was established: %q", forbidden)
				}
			}
		})
	}
}
