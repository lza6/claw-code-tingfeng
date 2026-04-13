package cli

import (
	"errors"
	"os"
	"strings"
	"testing"
	"time"
)

func TestQueueControlReminderDedupesByKey(t *testing.T) {
	runDir := t.TempDir()
	if err := EnsureControlState(runDir); err != nil {
		t.Fatalf("EnsureControlState: %v", err)
	}

	first, err := QueueControlReminder(runDir, "master-wake", "control-cycle", "gx-demo:master")
	if err != nil {
		t.Fatalf("QueueControlReminder first: %v", err)
	}
	second, err := QueueControlReminder(runDir, "master-wake", "control-cycle", "gx-demo:master")
	if err != nil {
		t.Fatalf("QueueControlReminder second: %v", err)
	}

	reminders, err := LoadControlReminders(ControlRemindersPath(runDir))
	if err != nil {
		t.Fatalf("LoadControlReminders: %v", err)
	}
	if len(reminders.Items) != 1 {
		t.Fatalf("reminders len = %d, want 1", len(reminders.Items))
	}
	if second.ReminderID != first.ReminderID {
		t.Fatalf("second reminder id = %q, want %q", second.ReminderID, first.ReminderID)
	}
}

func TestQueueControlReminderReusesSuppressedReminderRecord(t *testing.T) {
	runDir := t.TempDir()
	if err := EnsureControlState(runDir); err != nil {
		t.Fatalf("EnsureControlState: %v", err)
	}

	first, err := QueueControlReminderWithEngine(runDir, "session-wake:session-1", "session-inbox-unread", "gx-demo:session-1", "codex")
	if err != nil {
		t.Fatalf("QueueControlReminderWithEngine first: %v", err)
	}
	if err := SuppressControlReminder(runDir, "session-wake:session-1"); err != nil {
		t.Fatalf("SuppressControlReminder: %v", err)
	}

	second, err := QueueControlReminderWithEngine(runDir, "session-wake:session-1", "session-inbox-unread", "gx-demo:session-1", "claude-code")
	if err != nil {
		t.Fatalf("QueueControlReminderWithEngine second: %v", err)
	}

	reminders, err := LoadControlReminders(ControlRemindersPath(runDir))
	if err != nil {
		t.Fatalf("LoadControlReminders: %v", err)
	}
	if len(reminders.Items) != 1 {
		t.Fatalf("reminders len = %d, want 1", len(reminders.Items))
	}
	if second.ReminderID != first.ReminderID {
		t.Fatalf("second reminder id = %q, want reused %q", second.ReminderID, first.ReminderID)
	}
	if reminders.Items[0].Suppressed {
		t.Fatalf("reused reminder should be unsuppressed: %+v", reminders.Items[0])
	}
	if reminders.Items[0].Engine != "claude-code" {
		t.Fatalf("reused reminder engine = %q, want claude-code", reminders.Items[0].Engine)
	}
}

func TestQueueControlReminderRefreshesExistingReminderFields(t *testing.T) {
	runDir := t.TempDir()
	if err := EnsureControlState(runDir); err != nil {
		t.Fatalf("EnsureControlState: %v", err)
	}

	if _, err := QueueControlReminderWithEngine(runDir, "master-wake", "control-cycle", "gx-old:master", "codex"); err != nil {
		t.Fatalf("QueueControlReminderWithEngine first: %v", err)
	}
	updated, err := QueueControlReminderWithEngine(runDir, "master-wake", "identity-fence-changed", "gx-new:master", "claude-code")
	if err != nil {
		t.Fatalf("QueueControlReminderWithEngine second: %v", err)
	}

	if updated.Target != "gx-new:master" || updated.Engine != "claude-code" || updated.Reason != "identity-fence-changed" {
		t.Fatalf("updated reminder = %+v", updated)
	}
}

func TestDeliverDueControlRemindersRespectsCooldownAndCreatesDelivery(t *testing.T) {
	runDir := t.TempDir()
	if err := EnsureControlState(runDir); err != nil {
		t.Fatalf("EnsureControlState: %v", err)
	}
	if _, err := QueueControlReminder(runDir, "master-wake", "control-cycle", "gx-demo:master"); err != nil {
		t.Fatalf("QueueControlReminder: %v", err)
	}

	calls := 0
	send := func(target, engine string) (TransportDeliveryOutcome, error) {
		calls++
		return TransportDeliveryOutcome{SubmitMode: "payload_enter", TransportState: "queued"}, nil
	}

	start := time.Now().UTC()
	if err := DeliverDueControlReminders(runDir, "codex", 5*time.Minute, send); err != nil {
		t.Fatalf("DeliverDueControlReminders first: %v", err)
	}
	if err := DeliverDueControlReminders(runDir, "codex", 5*time.Minute, send); err != nil {
		t.Fatalf("DeliverDueControlReminders second: %v", err)
	}

	if calls != 1 {
		t.Fatalf("deliver calls = %d, want 1", calls)
	}
	reminders, err := LoadControlReminders(ControlRemindersPath(runDir))
	if err != nil {
		t.Fatalf("LoadControlReminders: %v", err)
	}
	if len(reminders.Items) != 1 {
		t.Fatalf("reminders len = %d, want 1", len(reminders.Items))
	}
	if reminders.Items[0].Attempts != 1 || reminders.Items[0].CooldownUntil == "" {
		t.Fatalf("unexpected reminder: %+v", reminders.Items[0])
	}
	cooldownUntil, err := time.Parse(time.RFC3339, reminders.Items[0].CooldownUntil)
	if err != nil {
		t.Fatalf("parse cooldown_until: %v", err)
	}
	if cooldownUntil.Before(start.Add(4 * time.Minute)) {
		t.Fatalf("cooldown_until = %s, want interval-derived cooldown well above 4 minutes", reminders.Items[0].CooldownUntil)
	}
	deliveries, err := LoadControlDeliveries(ControlDeliveriesPath(runDir))
	if err != nil {
		t.Fatalf("LoadControlDeliveries: %v", err)
	}
	if len(deliveries.Items) != 1 || deliveries.Items[0].Status != "accepted" || deliveries.Items[0].DedupeKey != "master-wake" {
		t.Fatalf("unexpected deliveries: %+v", deliveries.Items)
	}
}

func TestDeliverDueControlRemindersUsesShortBufferedCooldown(t *testing.T) {
	runDir := t.TempDir()
	if err := EnsureControlState(runDir); err != nil {
		t.Fatalf("EnsureControlState: %v", err)
	}
	if _, err := QueueControlReminder(runDir, "session-wake:session-1", "session-inbox-unread", "gx-demo:session-1"); err != nil {
		t.Fatalf("QueueControlReminder: %v", err)
	}

	start := time.Now().UTC()
	if err := DeliverDueControlReminders(runDir, "codex", 5*time.Minute, func(target, engine string) (TransportDeliveryOutcome, error) {
		return TransportDeliveryOutcome{SubmitMode: "enter_only_repair", TransportState: "buffered_input"}, nil
	}); err != nil {
		t.Fatalf("DeliverDueControlReminders: %v", err)
	}

	reminders, err := LoadControlReminders(ControlRemindersPath(runDir))
	if err != nil {
		t.Fatalf("LoadControlReminders: %v", err)
	}
	if len(reminders.Items) != 1 {
		t.Fatalf("reminders len = %d, want 1", len(reminders.Items))
	}
	cooldownUntil, err := time.Parse(time.RFC3339, reminders.Items[0].CooldownUntil)
	if err != nil {
		t.Fatalf("parse cooldown_until: %v", err)
	}
	if cooldownUntil.After(start.Add(31 * time.Second)) {
		t.Fatalf("buffered cooldown = %s, want short repair window", reminders.Items[0].CooldownUntil)
	}
}

func TestDeliverDueControlRemindersBacksOffFailedRetries(t *testing.T) {
	runDir := t.TempDir()
	if err := EnsureControlState(runDir); err != nil {
		t.Fatalf("EnsureControlState: %v", err)
	}
	if _, err := QueueControlReminder(runDir, "master-wake", "control-cycle", "gx-demo:master"); err != nil {
		t.Fatalf("QueueControlReminder: %v", err)
	}

	if err := DeliverDueControlReminders(runDir, "codex", time.Minute, func(target, engine string) (TransportDeliveryOutcome, error) {
		return TransportDeliveryOutcome{}, errors.New("tmux unavailable")
	}); err != nil {
		t.Fatalf("DeliverDueControlReminders first: %v", err)
	}

	reminders, err := LoadControlReminders(ControlRemindersPath(runDir))
	if err != nil {
		t.Fatalf("LoadControlReminders: %v", err)
	}
	if len(reminders.Items) != 1 {
		t.Fatalf("reminders len = %d, want 1", len(reminders.Items))
	}
	firstCooldown, err := time.Parse(time.RFC3339, reminders.Items[0].CooldownUntil)
	if err != nil {
		t.Fatalf("parse first cooldown: %v", err)
	}

	reminders.Items[0].CooldownUntil = time.Now().UTC().Add(-time.Second).Format(time.RFC3339)
	if err := SaveControlReminders(ControlRemindersPath(runDir), reminders); err != nil {
		t.Fatalf("SaveControlReminders: %v", err)
	}
	if err := DeliverDueControlReminders(runDir, "codex", time.Minute, func(target, engine string) (TransportDeliveryOutcome, error) {
		return TransportDeliveryOutcome{}, errors.New("tmux unavailable")
	}); err != nil {
		t.Fatalf("DeliverDueControlReminders second: %v", err)
	}

	reminders, err = LoadControlReminders(ControlRemindersPath(runDir))
	if err != nil {
		t.Fatalf("LoadControlReminders second: %v", err)
	}
	secondCooldown, err := time.Parse(time.RFC3339, reminders.Items[0].CooldownUntil)
	if err != nil {
		t.Fatalf("parse second cooldown: %v", err)
	}
	if !secondCooldown.After(firstCooldown) {
		t.Fatalf("second cooldown %s should back off beyond first %s", secondCooldown, firstCooldown)
	}
}

func TestLoadControlRemindersReadsLegacyAckedAtAndSaveWritesResolvedAt(t *testing.T) {
	runDir := t.TempDir()
	path := ControlRemindersPath(runDir)
	if err := os.MkdirAll(ControlDir(runDir), 0o755); err != nil {
		t.Fatalf("MkdirAll: %v", err)
	}
	raw := `{"version":1,"items":[{"reminder_id":"rem-1","dedupe_key":"master-wake","acked_at":"2026-03-26T00:00:00Z"}]}`
	if err := os.WriteFile(path, []byte(raw), 0o644); err != nil {
		t.Fatalf("WriteFile: %v", err)
	}

	reminders, err := LoadControlReminders(path)
	if err != nil {
		t.Fatalf("LoadControlReminders: %v", err)
	}
	if len(reminders.Items) != 1 || reminders.Items[0].ResolvedAt != "2026-03-26T00:00:00Z" {
		t.Fatalf("legacy acked_at not loaded into ResolvedAt: %+v", reminders.Items)
	}
	if err := SaveControlReminders(path, reminders); err != nil {
		t.Fatalf("SaveControlReminders: %v", err)
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("ReadFile: %v", err)
	}
	text := string(data)
	if !strings.Contains(text, "\"resolved_at\": \"2026-03-26T00:00:00Z\"") {
		t.Fatalf("saved reminders should contain resolved_at:\n%s", text)
	}
	if strings.Contains(text, "\"acked_at\":") {
		t.Fatalf("saved reminders should not contain legacy acked_at:\n%s", text)
	}
}
