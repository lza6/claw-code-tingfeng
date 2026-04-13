package cli

import (
	"fmt"
	"os"
)

// Archive creates a git tag for a session branch, preserving it.
func Archive(projectRoot string, args []string) error {
	if printUsageIfHelp(args, "usage: goalx archive [--run NAME] <session-name>") {
		return nil
	}
	runName, rest, err := extractRunFlag(args)
	if err != nil {
		return err
	}
	if len(rest) != 1 {
		return fmt.Errorf("usage: goalx archive [--run NAME] <session-name>")
	}
	sessionName := rest[0]

	rc, err := ResolveRun(projectRoot, runName)
	if err != nil {
		return err
	}

	idx, err := parseSessionIndex(sessionName)
	if err != nil {
		return err
	}
	ok, err := hasSessionIndex(rc.RunDir, idx)
	if err != nil {
		return err
	}
	if !ok {
		return fmt.Errorf("session %q out of range for run %q", sessionName, rc.Name)
	}

	branch := fmt.Sprintf("goalx/%s/%d", rc.Config.Name, idx)
	tag := fmt.Sprintf("goalx-archive/%s/%d", rc.Config.Name, idx)

	if err := TagArchive(rc.ProjectRoot, branch, tag); err != nil {
		return fmt.Errorf("tag %s: %w", tag, err)
	}
	fmt.Printf("Archived %s as tag %s\n", sessionName, tag)

	// Auto-save run artifacts on first archive
	if _, err := ResolveSavedRunLocation(rc.ProjectRoot, rc.Config.Name); os.IsNotExist(err) {
		if saveErr := Save(rc.ProjectRoot, []string{rc.Name}); saveErr != nil {
			fmt.Fprintf(os.Stderr, "warning: auto-save failed: %v\n", saveErr)
		}
	} else if err != nil {
		return err
	}

	return nil
}
