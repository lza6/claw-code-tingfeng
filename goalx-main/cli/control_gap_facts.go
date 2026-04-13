package cli

import (
	"slices"
	"strings"
)

type ControlGapFacts struct {
	StatusDrift                  bool     `json:"status_drift,omitempty"`
	CoordinationStale            bool     `json:"coordination_stale,omitempty"`
	SerializedRequiredFrontier   bool     `json:"serialized_required_frontier,omitempty"`
	DispatchableParallelFrontier bool     `json:"dispatchable_parallel_frontier,omitempty"`
	ReusableCapacityPresent      bool     `json:"reusable_capacity_present,omitempty"`
	OpenRequiredCount            int      `json:"open_required_count,omitempty"`
	ActiveRequiredOwnerCount     int      `json:"active_required_owner_count,omitempty"`
	ActiveRequiredOwners         []string `json:"active_required_owners,omitempty"`
	ReusableSessions             []string `json:"reusable_sessions,omitempty"`
	DispatchableRequiredIDs      []string `json:"dispatchable_required_ids,omitempty"`
	DispatchableSources          []string `json:"dispatchable_sources,omitempty"`
	StatusUpdatedAt              string   `json:"status_updated_at,omitempty"`
	CoordinationUpdatedAt        string   `json:"coordination_updated_at,omitempty"`
	LatestControlChangeAt        string   `json:"latest_control_change_at,omitempty"`
}

func BuildControlGapFacts(runDir string) (*ControlGapFacts, error) {
	status, err := LoadRunStatusRecord(RunStatusPath(runDir))
	if err != nil {
		return nil, err
	}
	statusComparison, err := BuildRunStatusComparison(runDir)
	if err != nil {
		return nil, err
	}
	coord, err := LoadCoordinationState(CoordinationPath(runDir))
	if err != nil {
		return nil, err
	}
	sessionState, err := LoadSessionsRuntimeState(SessionsRuntimeStatePath(runDir))
	if err != nil {
		return nil, err
	}
	coverage, err := BuildRequiredCoverage(runDir)
	if err != nil {
		return nil, err
	}
	latestControlChangeAt, err := latestControlGapChangeAt(runDir)
	if err != nil {
		return nil, err
	}

	facts := &ControlGapFacts{
		OpenRequiredCount:     len(coverage.OpenRequiredIDs),
		StatusUpdatedAt:       controlGapStatusUpdatedAt(status),
		CoordinationUpdatedAt: controlGapCoordinationUpdatedAt(coord),
		LatestControlChangeAt: latestControlChangeAt,
	}
	if statusComparison != nil {
		facts.StatusDrift = controlGapStatusDrift(statusComparison)
	}

	reusable := append([]string{}, coverage.IdleReusableSessions...)
	reusable = append(reusable, coverage.ParkedReusableSessions...)
	slices.Sort(reusable)
	facts.ReusableSessions = reusable
	facts.ReusableCapacityPresent = len(reusable) > 0

	facts.ActiveRequiredOwners = activeRequiredOwnerNames(coverage, coord, sessionState)
	facts.ActiveRequiredOwnerCount = len(facts.ActiveRequiredOwners)
	facts.DispatchableRequiredIDs, facts.DispatchableSources = dispatchableParallelFrontierFacts(coverage, coord, facts.ActiveRequiredOwners)

	if coordinationUpdatedAt, ok := parseRFC3339Time(facts.CoordinationUpdatedAt); ok {
		if latestControlChange, ok := parseRFC3339Time(facts.LatestControlChangeAt); ok && latestControlChange.After(coordinationUpdatedAt) {
			facts.CoordinationStale = true
		}
	}

	if coverage.RequiredPresent &&
		facts.OpenRequiredCount > 1 &&
		facts.ActiveRequiredOwnerCount == 1 &&
		facts.ReusableCapacityPresent &&
		len(coverage.UnmappedRequiredIDs) == 0 &&
		len(coverage.MasterOrphanedRequiredIDs) == 0 &&
		len(coverage.PrematureBlockedRequiredIDs) == 0 {
		facts.SerializedRequiredFrontier = true
	}
	if facts.ReusableCapacityPresent && len(facts.DispatchableRequiredIDs) > 0 {
		facts.DispatchableParallelFrontier = true
	}

	return facts, nil
}

func controlGapStatusDrift(comparison *RunStatusComparison) bool {
	if comparison == nil {
		return false
	}
	if comparison.StatusRequiredRemaining != nil && comparison.GoalRequiredRemaining != nil && !comparison.RequiredRemainingMatch {
		return true
	}
	if comparison.StatusOpenRequiredIDsRecorded && !comparison.OpenRequiredIDsMatch {
		return true
	}
	if comparison.StatusActiveSessionsRecorded && !comparison.ActiveSessionsMatch {
		return true
	}
	return false
}

func activeRequiredOwnerNames(coverage RequiredCoverage, coord *CoordinationState, sessionState *SessionsRuntimeState) []string {
	if coord == nil || coord.Required == nil || len(coverage.OpenRequiredIDs) == 0 {
		return nil
	}
	owners := map[string]struct{}{}
	for _, id := range coverage.OpenRequiredIDs {
		required, ok := coord.Required[id]
		if !ok {
			continue
		}
		switch strings.TrimSpace(required.ExecutionState) {
		case coordinationRequiredExecutionStateActive, coordinationRequiredExecutionStateProbing, coordinationRequiredExecutionStateWaiting:
		default:
			continue
		}
		for _, owner := range coverage.LaneCoverage[id] {
			if !isSessionOwnerToken(owner) {
				continue
			}
			switch coverageSessionLifecycleState(owner, sessionState, coord) {
			case "active", "progress", "working", "idle":
				owners[owner] = struct{}{}
			}
		}
	}
	if len(owners) == 0 {
		return nil
	}
	names := make([]string, 0, len(owners))
	for owner := range owners {
		names = append(names, owner)
	}
	slices.Sort(names)
	return names
}

func dispatchableParallelFrontierFacts(coverage RequiredCoverage, coord *CoordinationState, activeOwners []string) ([]string, []string) {
	if coord == nil || coord.Sessions == nil || len(coverage.OpenRequiredIDs) == 0 {
		return nil, nil
	}
	activeSet := map[string]struct{}{}
	for _, owner := range activeOwners {
		activeSet[strings.TrimSpace(owner)] = struct{}{}
	}
	requiredSet := map[string]struct{}{}
	sourceSet := map[string]struct{}{}
	for sessionName, session := range coord.Sessions {
		for _, slice := range session.DispatchableSlices {
			covers := compactStrings(slice.CoversRequired)
			if len(covers) == 0 {
				continue
			}
			for _, requiredID := range covers {
				if !containsString(coverage.OpenRequiredIDs, requiredID) {
					continue
				}
				activelyCovered := false
				for _, owner := range coverage.LaneCoverage[requiredID] {
					if _, ok := activeSet[owner]; ok {
						activelyCovered = true
						break
					}
				}
				if activelyCovered {
					continue
				}
				requiredSet[requiredID] = struct{}{}
				sourceSet[sessionName] = struct{}{}
			}
		}
	}
	if len(requiredSet) == 0 {
		return nil, nil
	}
	requiredIDs := make([]string, 0, len(requiredSet))
	for requiredID := range requiredSet {
		requiredIDs = append(requiredIDs, requiredID)
	}
	sources := make([]string, 0, len(sourceSet))
	for source := range sourceSet {
		sources = append(sources, source)
	}
	slices.Sort(requiredIDs)
	slices.Sort(sources)
	return requiredIDs, sources
}

func latestControlGapChangeAt(runDir string) (string, error) {
	latest := ""

	integration, err := LoadIntegrationState(IntegrationStatePath(runDir))
	if err != nil {
		return "", err
	}
	if integration != nil {
		latest = latestRFC3339(latest, strings.TrimSpace(integration.UpdatedAt))
	}

	evolveFacts, err := LoadCurrentEvolveFacts(runDir)
	if err != nil {
		return "", err
	}
	if evolveFacts != nil {
		latest = latestRFC3339(latest, strings.TrimSpace(evolveFacts.LastManagementEventAt))
	}

	operations, err := LoadControlOperationsState(ControlOperationsPath(runDir))
	if err != nil {
		return "", err
	}
	if operations != nil {
		for target, op := range operations.Targets {
			if target == BoundaryEstablishmentOperationKey() {
				continue
			}
			latest = latestRFC3339(latest, strings.TrimSpace(op.CommittedAt), strings.TrimSpace(op.UpdatedAt))
		}
	}

	return latest, nil
}

func controlGapStatusUpdatedAt(status *RunStatusRecord) string {
	if status == nil {
		return ""
	}
	return strings.TrimSpace(status.UpdatedAt)
}

func controlGapCoordinationUpdatedAt(coord *CoordinationState) string {
	if coord == nil {
		return ""
	}
	return strings.TrimSpace(coord.UpdatedAt)
}
