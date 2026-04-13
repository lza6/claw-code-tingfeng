package cli

import (
	"fmt"
	"strings"
)

const repairUsage = "usage: goalx repair [--run NAME] [--all-stopped] [--facts-only]"

func Repair(projectRoot string, args []string) error {
	if printUsageIfHelp(args, repairUsage) {
		return nil
	}
	runName, rest, err := extractRunFlag(args)
	if err != nil {
		return err
	}
	factsOnly := false
	allStopped := false
	filtered := make([]string, 0, len(rest))
	for _, arg := range rest {
		if arg == "--facts-only" {
			factsOnly = true
			continue
		}
		if arg == "--all-stopped" {
			allStopped = true
			continue
		}
		filtered = append(filtered, arg)
	}
	rest = filtered
	if runName == "" && len(rest) == 1 {
		runName = rest[0]
		rest = nil
	}
	if len(rest) > 0 {
		return fmt.Errorf(repairUsage)
	}
	if allStopped && runName != "" {
		return fmt.Errorf("goalx repair accepts either --run NAME or --all-stopped, not both")
	}
	if allStopped {
		return repairAllStoppedRuns(projectRoot, factsOnly)
	}

	rc, err := ResolveRun(projectRoot, runName)
	if err != nil {
		return err
	}
	if factsOnly {
		return repairFactsOnlyRun(rc, true, "facts_only")
	}
	if !runLifecycleRepairable(runLifecycleLabel(rc.RunDir)) {
		return fmt.Errorf("goalx repair only repairs inactive runs with stopped or stranded lifecycle")
	}
	if err := repairInactiveSemanticSurfaces(rc.RunDir, inactiveSemanticRepairOptions{Origin: "repair"}); err != nil {
		return err
	}
	if err := repairFactsOnlyRun(rc, false, "semantic_and_facts"); err != nil {
		return err
	}
	fmt.Printf("Repaired inactive semantic surfaces for run '%s'.\n", rc.Name)
	return nil
}

func repairAllStoppedRuns(projectRoot string, factsOnly bool) error {
	states, err := listDerivedRunStates(projectRoot)
	if err != nil {
		return err
	}
	repaired := 0
	for _, state := range states {
		if strings.TrimSpace(state.Status) != "stopped" {
			continue
		}
		rc, err := buildRunContext(projectRoot, state.RunDir, state.Name)
		if err != nil {
			return err
		}
		if factsOnly {
			if err := repairFactsOnlyRun(rc, false, "facts_only"); err != nil {
				return err
			}
		} else {
			if err := repairInactiveSemanticSurfaces(rc.RunDir, inactiveSemanticRepairOptions{Origin: "repair"}); err != nil {
				return err
			}
			if err := repairFactsOnlyRun(rc, false, "semantic_and_facts"); err != nil {
				return err
			}
		}
		repaired++
	}
	if factsOnly {
		fmt.Printf("Repaired computed facts for %d stopped runs.\n", repaired)
	} else {
		fmt.Printf("Repaired stopped semantic surfaces for %d runs.\n", repaired)
	}
	return nil
}

func runLifecycleRepairable(lifecycle string) bool {
	switch strings.TrimSpace(lifecycle) {
	case "stopped", "stranded":
		return true
	default:
		return false
	}
}

func repairFactsOnlyRun(rc *RunContext, announce bool, mode string) error {
	if rc == nil {
		return nil
	}
	appendAuditLog(rc.RunDir, "manual_repair mode=%s lifecycle=%s", strings.TrimSpace(mode), blankAsUnknown(runLifecycleLabel(rc.RunDir)))
	if err := refreshDisplayFacts(rc); err != nil {
		return err
	}
	if announce {
		fmt.Printf("Repaired computed facts for run '%s'.\n", rc.Name)
	}
	return nil
}
