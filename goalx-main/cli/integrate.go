package cli

import (
	"fmt"
	"os"
	"strings"
	"time"
)

const integrateHelpText = `usage: goalx integrate [--run NAME] --method METHOD --from SOURCE[,SOURCE...]

- record a master-owned integration experiment for the current run-root HEAD
- requires the run-root worktree to be clean and already contain the integrated result
- does not merge branches for you; it records the lineage of the current run-root state
- SOURCE selectors must be canonical contributors such as session-N or run-root
- supported methods: manual_merge, partial_adopt, cherry_pick, consolidate`

func Integrate(projectRoot string, args []string) error {
	if printUsageIfHelp(args, integrateHelpText) {
		return nil
	}
	runName, rest, err := extractRunFlag(args)
	if err != nil {
		return err
	}

	var method string
	var sourceSelectors []string
	for i := 0; i < len(rest); i++ {
		switch rest[i] {
		case "--method":
			if i+1 >= len(rest) {
				return fmt.Errorf("missing value for --method")
			}
			i++
			method = strings.TrimSpace(rest[i])
		case "--from":
			if i+1 >= len(rest) {
				return fmt.Errorf("missing value for --from")
			}
			i++
			sourceSelectors = append(sourceSelectors, splitListFlag(rest[i])...)
		default:
			if strings.HasPrefix(rest[i], "-") {
				return fmt.Errorf("unknown flag %q", rest[i])
			}
			return fmt.Errorf(integrateHelpText)
		}
	}
	if method == "" {
		return fmt.Errorf("--method is required")
	}
	if _, ok := allowedIntegrationMethods[method]; !ok || method == "keep" {
		return fmt.Errorf("invalid --method %q (expected manual_merge, partial_adopt, cherry_pick, or consolidate)", method)
	}
	if len(sourceSelectors) == 0 {
		return fmt.Errorf("--from is required")
	}

	rc, err := ResolveRun(projectRoot, runName)
	if err != nil {
		return err
	}
	runWT := RunWorktreePath(rc.RunDir)
	if info, err := os.Stat(runWT); err != nil || !info.IsDir() {
		if err == nil {
			err = fmt.Errorf("not a directory")
		}
		return fmt.Errorf("run-root worktree missing at %s: %w", runWT, err)
	}
	dirtyPaths, err := dirtyWorktreePaths(runWT)
	if err != nil {
		return fmt.Errorf("inspect run-root worktree: %w", err)
	}
	if len(dirtyPaths) > 0 {
		return fmt.Errorf("run-root worktree %s has uncommitted changes (%s); commit or discard them before goalx integrate", runWT, summarizeDirtyPaths(dirtyPaths))
	}

	var created ExperimentCreatedBody
	if err := withExclusiveFileLock(IntegrationStatePath(rc.RunDir), func() error {
		current, err := LoadIntegrationState(IntegrationStatePath(rc.RunDir))
		if err != nil {
			return fmt.Errorf("load integration state: %w", err)
		}
		if current == nil {
			return fmt.Errorf("integration state missing at %s", IntegrationStatePath(rc.RunDir))
		}
		sources, err := resolveIntegrationSourceExperimentIDs(rc.RunDir, current, sourceSelectors)
		if err != nil {
			return err
		}
		currentCommit, err := gitHeadRevision(runWT)
		if err != nil {
			return fmt.Errorf("resolve run-root HEAD: %w", err)
		}
		if currentCommit == current.CurrentCommit {
			return fmt.Errorf("run-root HEAD is unchanged from current integrated commit %s; goalx integrate only records a new integrated result after the run-root state changes", current.CurrentCommit)
		}

		created = ExperimentCreatedBody{
			ExperimentID:     newExperimentID(),
			Session:          "master",
			Branch:           fmt.Sprintf("goalx/%s/root", rc.Config.Name),
			Worktree:         runWT,
			BaseRef:          current.CurrentBranch,
			BaseExperimentID: current.CurrentExperimentID,
			CreatedAt:        time.Now().UTC().Format(time.RFC3339),
		}
		if err := appendExperimentCreated(rc.RunDir, created); err != nil {
			return fmt.Errorf("append experiment.created: %w", err)
		}
		return recordIntegrationLocked(rc.RunDir, IntegrationRecord{
			ResultExperimentID:  created.ExperimentID,
			ResultBranch:        created.Branch,
			ResultCommit:        currentCommit,
			Method:              method,
			SourceExperimentIDs: sources,
		})
	}); err != nil {
		return err
	}
	fmt.Printf("Integration recorded: %s\n", IntegrationStatePath(rc.RunDir))
	fmt.Printf("Current experiment: %s\n", created.ExperimentID)
	return nil
}

func resolveIntegrationSourceExperimentIDs(runDir string, current *IntegrationState, selectors []string) ([]string, error) {
	if current == nil {
		return nil, fmt.Errorf("integration state is required")
	}
	existing, err := loadExperimentExistence(runDir)
	if err != nil {
		return nil, err
	}
	resolved := make([]string, 0, len(selectors))
	seen := make(map[string]struct{}, len(selectors))
	for _, raw := range selectors {
		selector := strings.TrimSpace(raw)
		if selector == "" {
			return nil, fmt.Errorf("empty --from source selector")
		}
		var experimentID string
		switch {
		case selector == "run-root":
			experimentID = current.CurrentExperimentID
		default:
			if _, err := parseSessionIndex(selector); err != nil {
				return nil, fmt.Errorf("invalid --from source %q (expected session-N or run-root)", selector)
			}
			identity, err := RequireSessionIdentity(runDir, selector)
			if err != nil {
				return nil, fmt.Errorf("load %s identity: %w", selector, err)
			}
			experimentID = strings.TrimSpace(identity.ExperimentID)
			if experimentID == "" {
				return nil, fmt.Errorf("session %s has no experiment_id", selector)
			}
		}
		if _, ok := existing[experimentID]; !ok {
			return nil, fmt.Errorf("source experiment %q is not present in %s", experimentID, ExperimentsLogPath(runDir))
		}
		if _, ok := seen[experimentID]; ok {
			return nil, fmt.Errorf("duplicate --from source resolves to experiment %q", experimentID)
		}
		seen[experimentID] = struct{}{}
		resolved = append(resolved, experimentID)
	}
	return resolved, nil
}

func loadExperimentExistence(runDir string) (map[string]struct{}, error) {
	events, err := LoadDurableLog(ExperimentsLogPath(runDir), DurableSurfaceExperiments)
	if err != nil {
		return nil, fmt.Errorf("load experiments ledger: %w", err)
	}
	existing := make(map[string]struct{}, len(events))
	for _, event := range events {
		if event.Kind != "experiment.created" {
			continue
		}
		var body ExperimentCreatedBody
		if err := decodeStrictJSON(event.Body, &body); err != nil {
			return nil, fmt.Errorf("parse %s entry: %w", ExperimentsLogPath(runDir), err)
		}
		existing[strings.TrimSpace(body.ExperimentID)] = struct{}{}
	}
	return existing, nil
}
