package cli

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

// GenerateAdapter configures a transport-reliability hook in a worktree.
// The hook ensures the session checks its inbox before exiting, guaranteeing
// message delivery — this is infrastructure, not policy.
func GenerateAdapter(engine, worktreePath, inboxPath, cursorPath string) error {
	if engine != "claude-code" {
		return nil
	}

	quotedInboxPath := shellQuote(inboxPath)
	quotedCursorPath := shellQuote(cursorPath)
	quotedInboxMessage := shellQuote("INBOX PENDING: read " + inboxPath + " and process new session instructions now")
	stopCmd := fmt.Sprintf(
		`last_id=$(tail -n 1 %s 2>/dev/null | sed -n 's/.*"id":[[:space:]]*\([0-9][0-9]*\).*/\1/p'); seen_id=$(sed -n 's/.*"last_seen_id":[[:space:]]*\([0-9][0-9]*\).*/\1/p' %s 2>/dev/null | tail -n 1); if [ -n "$last_id" ]; then if [ -z "$seen_id" ]; then seen_id=0; fi; if [ "$last_id" -gt "$seen_id" ]; then printf '%%s\n' %s >&2; exit 2; fi; fi`,
		quotedInboxPath, quotedCursorPath, quotedInboxMessage,
	)
	return appendClaudeHook(worktreePath, map[string]string{
		"event":   "Stop",
		"command": stopCmd,
	})
}

func appendClaudeHook(root string, hook map[string]string) error {
	claudeDir := filepath.Join(root, ".claude")
	if err := os.MkdirAll(claudeDir, 0o755); err != nil {
		return fmt.Errorf("create .claude dir: %w", err)
	}

	hooksPath := filepath.Join(claudeDir, "hooks.json")

	var doc map[string]json.RawMessage
	data, err := os.ReadFile(hooksPath)
	if err == nil {
		if err := json.Unmarshal(data, &doc); err != nil {
			return fmt.Errorf("parse hooks.json: %w", err)
		}
	} else if os.IsNotExist(err) {
		doc = make(map[string]json.RawMessage)
	} else {
		return fmt.Errorf("read hooks.json: %w", err)
	}

	var hooks []map[string]string
	if raw, ok := doc["hooks"]; ok {
		if err := json.Unmarshal(raw, &hooks); err != nil {
			return fmt.Errorf("parse hooks array: %w", err)
		}
	}
	for _, existing := range hooks {
		if existing["event"] == hook["event"] && existing["command"] == hook["command"] {
			return markHookFileAssumeUnchanged(root)
		}
	}
	hooks = append(hooks, hook)

	raw, err := json.Marshal(hooks)
	if err != nil {
		return fmt.Errorf("marshal hooks: %w", err)
	}
	doc["hooks"] = raw

	out, err := json.MarshalIndent(doc, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal hooks.json: %w", err)
	}
	if err := os.WriteFile(hooksPath, out, 0o644); err != nil {
		return fmt.Errorf("write hooks.json: %w", err)
	}
	return markHookFileAssumeUnchanged(root)
}

func markHookFileAssumeUnchanged(root string) error {
	// Only assume-unchanged if the file is already tracked by git.
	// If it's new (not in index), it won't be committed unless explicitly added.
	if err := exec.Command("git", "-C", root, "ls-files", "--error-unmatch", ".claude/hooks.json").Run(); err == nil {
		// File is tracked — mark assume-unchanged so our edits don't show in diffs
		return exec.Command("git", "-C", root, "update-index", "--assume-unchanged", ".claude/hooks.json").Run()
	}
	// File not tracked — nothing to do, it's already invisible to git
	return nil
}

func shellQuote(s string) string {
	return "'" + strings.ReplaceAll(s, "'", `'\''`) + "'"
}
