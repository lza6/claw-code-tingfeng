package cli

import (
	"strings"
	"testing"
)

func TestBuildEngineLaunchCommandInjectsRuntimeEnv(t *testing.T) {
	t.Setenv("HOME", "/tmp/goalx-home")
	t.Setenv("PATH", "/tmp/goalx-bin:/usr/bin")
	t.Setenv("OPENAI_API_KEY", "sk-test")
	t.Setenv("SSH_AUTH_SOCK", "/tmp/ssh.sock")
	t.Setenv("FOO_TOOLCHAIN_ROOT", "/opt/tools")
	t.Setenv("TERM", "dumb")
	t.Setenv("TMUX", "/tmp/tmux-should-not-propagate")
	t.Setenv("TMUX_PANE", "%42")
	t.Setenv("CODEX_THREAD_ID", "thread-should-not-propagate")

	cmd := buildEngineLaunchCommand("codex -m gpt-5.4 -a never -s danger-full-access", "/tmp/run/master.md")

	for _, want := range []string{
		"env ",
		"-u TERM",
		"-u TMUX",
		"-u TMUX_PANE",
		"-u CODEX_THREAD_ID",
		"FOO_TOOLCHAIN_ROOT='/opt/tools'",
		"HOME='/tmp/goalx-home'",
		"PATH='/tmp/goalx-bin:/usr/bin'",
		"OPENAI_API_KEY='sk-test'",
		"SSH_AUTH_SOCK='/tmp/ssh.sock'",
		"codex -m gpt-5.4 -a never -s danger-full-access",
		"'/tmp/run/master.md'",
	} {
		if !strings.Contains(cmd, want) {
			t.Fatalf("launch command missing %q:\n%s", want, cmd)
		}
	}
}
