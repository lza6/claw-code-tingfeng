package cli

import (
	"fmt"
	"os"
	"strings"
	"time"
)

type IntegrationRecord struct {
	ResultExperimentID  string
	ResultBranch        string
	ResultCommit        string
	Method              string
	SourceExperimentIDs []string
}

func recordIntegration(runDir string, record IntegrationRecord) error {
	return withExclusiveFileLock(IntegrationStatePath(runDir), func() error {
		return recordIntegrationLocked(runDir, record)
	})
}

func recordIntegrationLocked(runDir string, record IntegrationRecord) error {
	record.ResultExperimentID = strings.TrimSpace(record.ResultExperimentID)
	record.ResultBranch = strings.TrimSpace(record.ResultBranch)
	record.ResultCommit = strings.TrimSpace(record.ResultCommit)
	record.Method = strings.TrimSpace(record.Method)
	record.SourceExperimentIDs = normalizeIntegrationSourceExperimentIDs(record.SourceExperimentIDs)
	if err := validateIntegrationRecord(record); err != nil {
		return err
	}

	previous, err := LoadIntegrationState(IntegrationStatePath(runDir))
	if err != nil {
		return fmt.Errorf("load integration state: %w", err)
	}
	now := time.Now().UTC().Format(time.RFC3339)
	integrationID := newIntegrationID()
	next := &IntegrationState{
		Version:                 1,
		CurrentExperimentID:     record.ResultExperimentID,
		CurrentBranch:           record.ResultBranch,
		CurrentCommit:           record.ResultCommit,
		LastIntegrationID:       integrationID,
		LastMethod:              record.Method,
		LastSourceExperimentIDs: append([]string(nil), record.SourceExperimentIDs...),
		UpdatedAt:               now,
	}
	if err := SaveIntegrationState(IntegrationStatePath(runDir), next); err != nil {
		return fmt.Errorf("write integration state: %w", err)
	}
	if err := appendExperimentIntegrated(runDir, ExperimentIntegratedBody{
		IntegrationID:       integrationID,
		ResultExperimentID:  record.ResultExperimentID,
		SourceExperimentIDs: append([]string(nil), record.SourceExperimentIDs...),
		Method:              record.Method,
		ResultBranch:        record.ResultBranch,
		ResultCommit:        record.ResultCommit,
		RecordedAt:          now,
	}); err != nil {
		if previous != nil {
			_ = SaveIntegrationState(IntegrationStatePath(runDir), previous)
		} else {
			_ = os.Remove(IntegrationStatePath(runDir))
		}
		return fmt.Errorf("append experiment.integrated: %w", err)
	}
	return nil
}

func validateIntegrationRecord(record IntegrationRecord) error {
	if record.ResultExperimentID == "" {
		return fmt.Errorf("integration result_experiment_id is required")
	}
	if record.ResultBranch == "" {
		return fmt.Errorf("integration result_branch is required")
	}
	if record.ResultCommit == "" {
		return fmt.Errorf("integration result_commit is required")
	}
	if _, ok := allowedIntegrationMethods[record.Method]; !ok {
		return fmt.Errorf("integration method %q is not supported", record.Method)
	}
	if len(record.SourceExperimentIDs) == 0 {
		return fmt.Errorf("integration source_experiment_ids are required")
	}
	seen := make(map[string]struct{}, len(record.SourceExperimentIDs))
	for _, id := range record.SourceExperimentIDs {
		if id == "" {
			return fmt.Errorf("integration source_experiment_ids cannot be empty")
		}
		if _, ok := seen[id]; ok {
			return fmt.Errorf("duplicate source experiment_id %q", id)
		}
		seen[id] = struct{}{}
	}
	return nil
}

func normalizeIntegrationSourceExperimentIDs(ids []string) []string {
	out := make([]string, 0, len(ids))
	for _, id := range ids {
		out = append(out, strings.TrimSpace(id))
	}
	return out
}
