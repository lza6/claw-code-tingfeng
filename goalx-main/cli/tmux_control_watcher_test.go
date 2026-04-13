package cli

import (
	"testing"
	"time"
)

func TestParseTmuxControlOutputNotificationParsesPaneID(t *testing.T) {
	got, ok := parseTmuxControlOutputNotification("%output %12 hello\\040world")
	if !ok {
		t.Fatal("parseTmuxControlOutputNotification ok = false, want true")
	}
	if got.PaneID != "%12" {
		t.Fatalf("PaneID = %q, want %%12", got.PaneID)
	}
	if got.Value != "hello world" {
		t.Fatalf("Value = %q, want %q", got.Value, "hello world")
	}
}

func TestParseTmuxControlOutputNotificationParsesExtendedOutput(t *testing.T) {
	got, ok := parseTmuxControlOutputNotification("%extended-output %3 250 : queued\\040messages")
	if !ok {
		t.Fatal("parseTmuxControlOutputNotification ok = false, want true")
	}
	if got.PaneID != "%3" {
		t.Fatalf("PaneID = %q, want %%3", got.PaneID)
	}
	if got.Value != "queued messages" {
		t.Fatalf("Value = %q, want %q", got.Value, "queued messages")
	}
}

func TestParseTmuxControlOutputNotificationRejectsNonOutputLines(t *testing.T) {
	if _, ok := parseTmuxControlOutputNotification("%window-add @2"); ok {
		t.Fatal("parseTmuxControlOutputNotification ok = true, want false")
	}
}

func TestTransportWatcherRecordsPaneOutputTime(t *testing.T) {
	w := &TmuxControlWatcher{
		paneLastOutputAt: map[string]time.Time{},
	}
	before := time.Now().UTC()
	w.recordOutput("%7", "working")
	at, ok := w.snapshotLastOutputAt()["%7"]
	if !ok {
		t.Fatal("pane output time missing for %7")
	}
	if at.Before(before) {
		t.Fatalf("last output time = %v, want >= %v", at, before)
	}
}
