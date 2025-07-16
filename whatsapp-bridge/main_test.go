package main

import (
	"testing"
	"time"

	waProto "go.mau.fi/whatsmeow/binary/proto"
	"google.golang.org/protobuf/proto"
)

func TestExtractMediaInfoAudioDuplicateNames(t *testing.T) {
	// Create two audio messages with the same content but different timestamps
	audioMsg1 := &waProto.Message{
		AudioMessage: &waProto.AudioMessage{
			URL:           proto.String("https://example.com/audio1.ogg"),
			MediaKey:      []byte("key1"),
			FileSHA256:    []byte("sha1"),
			FileEncSHA256: []byte("encsha1"),
			FileLength:    proto.Uint64(1024),
		},
	}

	audioMsg2 := &waProto.Message{
		AudioMessage: &waProto.AudioMessage{
			URL:           proto.String("https://example.com/audio2.ogg"),
			MediaKey:      []byte("key2"),
			FileSHA256:    []byte("sha2"),
			FileEncSHA256: []byte("encsha2"),
			FileLength:    proto.Uint64(2048),
		},
	}

	// Extract media info from both messages with different timestamps
	// This should show that timestamps are now used correctly
	timestamp1 := time.Date(2024, 1, 1, 10, 30, 0, 0, time.UTC)
	timestamp2 := time.Date(2024, 1, 1, 11, 45, 0, 0, time.UTC)
	
	mediaType1, filename1, url1, mediaKey1, fileSHA256_1, fileEncSHA256_1, fileLength1 := extractMediaInfo(audioMsg1, timestamp1)
	mediaType2, filename2, url2, mediaKey2, fileSHA256_2, fileEncSHA256_2, fileLength2 := extractMediaInfo(audioMsg2, timestamp2)

	// Verify both are audio messages
	if mediaType1 != "audio" || mediaType2 != "audio" {
		t.Errorf("Expected both messages to be audio type, got %s and %s", mediaType1, mediaType2)
	}

	// The problem: filenames might be identical if processed within the same second
	// This test will fail intermittently because of the time.Now() usage
	if filename1 == filename2 {
		t.Errorf("Audio filenames should be unique but got identical names: %s", filename1)
	}

	// Verify URLs are different (they should be since they come from different messages)
	if url1 == url2 {
		t.Errorf("URLs should be different but got identical: %s", url1)
	}

	// Verify media keys are different
	if string(mediaKey1) == string(mediaKey2) {
		t.Errorf("Media keys should be different")
	}

	// Verify file lengths are different
	if fileLength1 == fileLength2 {
		t.Errorf("File lengths should be different but got %d and %d", fileLength1, fileLength2)
	}

	// Verify SHA256 hashes are different
	if string(fileSHA256_1) == string(fileSHA256_2) {
		t.Errorf("File SHA256 should be different")
	}

	if string(fileEncSHA256_1) == string(fileEncSHA256_2) {
		t.Errorf("File encrypted SHA256 should be different")
	}
}

func TestExtractMediaInfoAudioWithMessageTimestamp(t *testing.T) {
	// This test shows what the fix should do
	// Create audio message
	audioMsg := &waProto.Message{
		AudioMessage: &waProto.AudioMessage{
			URL:           proto.String("https://example.com/audio.ogg"),
			MediaKey:      []byte("key"),
			FileSHA256:    []byte("sha"),
			FileEncSHA256: []byte("encsha"),
			FileLength:    proto.Uint64(1024),
		},
	}

	// Extract media info - now uses the provided timestamp
	testTimestamp := time.Date(2024, 6, 15, 14, 30, 45, 0, time.UTC)
	mediaType, filename, _, _, _, _, _ := extractMediaInfo(audioMsg, testTimestamp)

	if mediaType != "audio" {
		t.Errorf("Expected audio type, got %s", mediaType)
	}

	// Filename should contain timestamp and UUID
	if len(filename) < 20 { // Should be at least "audio_20060102_150405_uuid.ogg"
		t.Errorf("Filename too short: %s", filename)
	}

	// Should end with .ogg
	if filename[len(filename)-4:] != ".ogg" {
		t.Errorf("Filename should end with .ogg, got %s", filename)
	}

	// Should contain "audio_" prefix
	if filename[:6] != "audio_" {
		t.Errorf("Filename should start with 'audio_', got %s", filename)
	}
}

func TestGenerateUUID(t *testing.T) {
	// Test that generateUUID produces unique values
	uuid1 := generateUUID()
	uuid2 := generateUUID()

	if uuid1 == uuid2 {
		t.Errorf("generateUUID should produce unique values but got identical: %s", uuid1)
	}

	// Should be 16 characters (8 bytes in hex)
	if len(uuid1) != 16 {
		t.Errorf("UUID should be 16 characters long, got %d: %s", len(uuid1), uuid1)
	}

	if len(uuid2) != 16 {
		t.Errorf("UUID should be 16 characters long, got %d: %s", len(uuid2), uuid2)
	}
}

func TestExtractMediaInfoAudioFilenameUniqueness(t *testing.T) {
	// Create multiple audio messages rapidly to test uniqueness
	audioMsg := &waProto.Message{
		AudioMessage: &waProto.AudioMessage{
			URL:           proto.String("https://example.com/audio.ogg"),
			MediaKey:      []byte("key"),
			FileSHA256:    []byte("sha"),
			FileEncSHA256: []byte("encsha"),
			FileLength:    proto.Uint64(1024),
		},
	}

	filenames := make(map[string]bool)
	duplicates := make([]string, 0)

	// Extract media info 100 times with different timestamps
	baseTime := time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC)
	for i := 0; i < 100; i++ {
		// Each message has a different timestamp (1 second apart)
		timestamp := baseTime.Add(time.Duration(i) * time.Second)
		_, filename, _, _, _, _, _ := extractMediaInfo(audioMsg, timestamp)
		
		if filenames[filename] {
			duplicates = append(duplicates, filename)
		}
		filenames[filename] = true
	}

	// This test should now pass since we use different timestamps for each message
	if len(duplicates) > 0 {
		t.Errorf("Found %d duplicate filenames: %v", len(duplicates), duplicates)
	}
}

func TestExtractMediaInfoShowsTimestampFix(t *testing.T) {
	// This test demonstrates that filenames now use the provided timestamp
	// instead of the current time, so messages sent at different times have different timestamps
	audioMsg := &waProto.Message{
		AudioMessage: &waProto.AudioMessage{
			URL:           proto.String("https://example.com/audio.ogg"),
			MediaKey:      []byte("key"),
			FileSHA256:    []byte("sha"),
			FileEncSHA256: []byte("encsha"),
			FileLength:    proto.Uint64(1024),
		},
	}

	// Get 10 filenames with different timestamps
	var filenames []string
	baseTime := time.Date(2024, 6, 21, 10, 0, 0, 0, time.UTC)
	for i := 0; i < 10; i++ {
		// Each message has a different timestamp (1 hour apart)
		timestamp := baseTime.Add(time.Duration(i) * time.Hour)
		_, filename, _, _, _, _, _ := extractMediaInfo(audioMsg, timestamp)
		filenames = append(filenames, filename)
	}

	// Now filenames should have different timestamp portions
	timestampPart := filenames[0][:21] // "audio_20240621_100000"
	
	allSameTimestamp := true
	for _, filename := range filenames {
		if filename[:21] != timestampPart {
			allSameTimestamp = false
			break
		}
	}

	// This assertion should now fail, showing that timestamps are properly different
	if !allSameTimestamp {
		t.Logf("Good! Timestamps are now different as expected: %v", filenames)
	} else {
		t.Errorf("UNEXPECTED: All audio files still get the same timestamp '%s'. This suggests the fix didn't work. Filenames: %v", timestampPart, filenames)
	}
}