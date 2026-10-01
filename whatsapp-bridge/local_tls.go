package main

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"errors"
	"math/big"
	"net"
	"os"
	"path/filepath"
	"time"
)

// The private installation directory holds the trust anchor and its key.
// Clients trust only this certificate, never a system-wide or remote CA.
func initializeLocalTLS(directory string) error {
	certPath := filepath.Join(directory, "bridge-cert.pem")
	keyPath := filepath.Join(directory, "bridge-key.pem")
	if _, err := os.Stat(certPath); err == nil {
		_, err = os.Stat(keyPath)
		return err
	} else if !errors.Is(err, os.ErrNotExist) {
		return err
	}
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		return err
	}
	serial, err := rand.Int(rand.Reader, new(big.Int).Lsh(big.NewInt(1), 128))
	if err != nil {
		return err
	}
	now := time.Now()
	template := &x509.Certificate{
		SerialNumber: serial, Subject: pkix.Name{CommonName: "WhatsApp Local bridge"},
		NotBefore: now.Add(-time.Hour), NotAfter: now.AddDate(10, 0, 0),
		KeyUsage:              x509.KeyUsageDigitalSignature,
		ExtKeyUsage:           []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
		IPAddresses:           []net.IP{net.ParseIP("127.0.0.1")},
		BasicConstraintsValid: true,
	}
	der, err := x509.CreateCertificate(rand.Reader, template, template, &key.PublicKey, key)
	if err != nil {
		return err
	}
	keyDER, err := x509.MarshalPKCS8PrivateKey(key)
	if err != nil {
		return err
	}
	// Write exclusively; never replace existing identity material silently.
	keyFile, err := os.OpenFile(keyPath, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		return err
	}
	err = pem.Encode(keyFile, &pem.Block{Type: "PRIVATE KEY", Bytes: keyDER})
	closeErr := keyFile.Close()
	if err != nil {
		return err
	}
	if closeErr != nil {
		return closeErr
	}
	certFile, err := os.OpenFile(certPath, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		return err
	}
	err = pem.Encode(certFile, &pem.Block{Type: "CERTIFICATE", Bytes: der})
	closeErr = certFile.Close()
	if err != nil {
		return err
	}
	return closeErr
}
