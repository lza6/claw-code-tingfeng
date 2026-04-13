package cli

import (
	"fmt"
	"time"

	goalx "github.com/vonbai/goalx"
)

func requireRunBudgetAvailable(runDir string, cfg *goalx.Config) error {
	if cfg == nil || cfg.Budget.MaxDuration <= 0 {
		return nil
	}
	runtimeState, err := LoadRunRuntimeState(RunRuntimeStatePath(runDir))
	if err != nil {
		return err
	}
	meta, err := LoadRunMetadata(RunMetadataPath(runDir))
	if err != nil {
		return err
	}
	budget := buildActivityBudget(cfg, runtimeState, meta, time.Now().UTC().Format(time.RFC3339))
	if !budget.Exhausted {
		return nil
	}
	return fmt.Errorf("run %q budget exhausted: %s", cfg.Name, formatBudgetSummary(budget))
}
