package goalx

import (
	"fmt"
	"strings"
)

type EffectiveSelectionPolicy struct {
	DisabledEngines  []string
	DisabledTargets  []string
	MasterCandidates []string
	WorkerCandidates []string
	MasterEffort     EffortLevel
	WorkerEffort     EffortLevel
}

type SelectionTarget struct {
	Engine string
	Model  string
}

func hasSelectionConfig(cfg SelectionConfig) bool {
	return len(cfg.DisabledEngines) > 0 ||
		len(cfg.DisabledTargets) > 0 ||
		len(cfg.MasterCandidates) > 0 ||
		len(cfg.WorkerCandidates) > 0 ||
		cfg.MasterEffort != "" ||
		cfg.WorkerEffort != ""
}

func copySelectionConfig(src SelectionConfig) SelectionConfig {
	return SelectionConfig{
		DisabledEngines:  append([]string(nil), src.DisabledEngines...),
		DisabledTargets:  append([]string(nil), src.DisabledTargets...),
		MasterCandidates: append([]string(nil), src.MasterCandidates...),
		WorkerCandidates: append([]string(nil), src.WorkerCandidates...),
		MasterEffort:     src.MasterEffort,
		WorkerEffort:     src.WorkerEffort,
	}
}

func normalizeSelectionConfig(cfg SelectionConfig, engines map[string]EngineConfig) (SelectionConfig, error) {
	var err error
	out := copySelectionConfig(cfg)
	if out.DisabledEngines, err = normalizeSelectionEngines(out.DisabledEngines, "selection.disabled_engines", engines); err != nil {
		return SelectionConfig{}, err
	}
	if out.DisabledTargets, err = normalizeSelectionTargets(out.DisabledTargets, "selection.disabled_targets", engines); err != nil {
		return SelectionConfig{}, err
	}
	if out.MasterCandidates, err = normalizeSelectionTargets(out.MasterCandidates, "selection.master_candidates", engines); err != nil {
		return SelectionConfig{}, err
	}
	if out.WorkerCandidates, err = normalizeSelectionTargets(out.WorkerCandidates, "selection.worker_candidates", engines); err != nil {
		return SelectionConfig{}, err
	}
	if err := validateEffortLevel(out.MasterEffort, "selection.master_effort"); err != nil {
		return SelectionConfig{}, err
	}
	if err := validateEffortLevel(out.WorkerEffort, "selection.worker_effort"); err != nil {
		return SelectionConfig{}, err
	}
	return out, nil
}

func normalizeSelectionEngines(values []string, field string, engines map[string]EngineConfig) ([]string, error) {
	if len(values) == 0 {
		return nil, nil
	}
	normalized := make([]string, 0, len(values))
	for _, raw := range values {
		name := strings.TrimSpace(raw)
		if name == "" {
			continue
		}
		if _, ok := engines[name]; !ok {
			return nil, fmt.Errorf("%s contains unknown engine %q", field, name)
		}
		normalized = append(normalized, name)
	}
	if len(normalized) == 0 {
		return nil, nil
	}
	if err := validateUniqueNames(normalized, field); err != nil {
		return nil, err
	}
	return normalized, nil
}

func normalizeSelectionTargets(values []string, field string, engines map[string]EngineConfig) ([]string, error) {
	if len(values) == 0 {
		return nil, nil
	}
	normalized := make([]string, 0, len(values))
	for i, raw := range values {
		raw = strings.TrimSpace(raw)
		if raw == "" {
			continue
		}
		target, err := parseSelectionTarget(raw, fmt.Sprintf("%s[%d]", field, i))
		if err != nil {
			return nil, err
		}
		formatted := formatSelectionTarget(target)
		if err := validateLaunchRequest(engines, LaunchRequest{Engine: target.Engine, Model: target.Model}, fmt.Sprintf("%s[%d]", field, i)); err != nil {
			return nil, err
		}
		normalized = append(normalized, formatted)
	}
	if len(normalized) == 0 {
		return nil, nil
	}
	if err := validateUniqueNames(normalized, field); err != nil {
		return nil, err
	}
	return normalized, nil
}

func parseSelectionTarget(raw string, field string) (SelectionTarget, error) {
	parts := strings.Split(raw, "/")
	if len(parts) != 2 {
		return SelectionTarget{}, fmt.Errorf("%s must be ENGINE/MODEL, got %q", field, raw)
	}
	engine := strings.TrimSpace(parts[0])
	model := strings.TrimSpace(parts[1])
	if engine == "" || model == "" {
		return SelectionTarget{}, fmt.Errorf("%s must be ENGINE/MODEL, got %q", field, raw)
	}
	return SelectionTarget{Engine: engine, Model: model}, nil
}

func formatSelectionTarget(target SelectionTarget) string {
	return strings.TrimSpace(target.Engine) + "/" + strings.TrimSpace(target.Model)
}

func DetectAvailableEngines(engines map[string]EngineConfig) map[string]bool {
	if len(engines) == 0 {
		engines = BuiltinEngines
	}
	available := make(map[string]bool, len(engines))
	for name, engine := range engines {
		binary := launchBinaryName(strings.ReplaceAll(engine.Command, "{model_id}", "model"))
		if binary == "" {
			continue
		}
		if commandExists(binary) {
			available[name] = true
		}
	}
	return available
}

func resolveEffectiveSelectionPolicy(cfg *Config, engines map[string]EngineConfig) (EffectiveSelectionPolicy, bool, error) {
	if cfg == nil {
		return EffectiveSelectionPolicy{}, false, fmt.Errorf("config is nil")
	}
	if hasSelectionConfig(cfg.Selection) {
		policy, err := compileExplicitSelectionPolicy(cfg.Selection, engines, DetectAvailableEngines(engines))
		return policy, true, err
	}
	return compileConfigSelectionPolicy(cfg), false, nil
}

func DeriveSelectionPolicy(cfg *Config) EffectiveSelectionPolicy {
	return compileConfigSelectionPolicy(cfg)
}

func compileExplicitSelectionPolicy(selection SelectionConfig, engines map[string]EngineConfig, availability map[string]bool) (EffectiveSelectionPolicy, error) {
	defaults, defaultsErr := builtinSelectionDefaults(availability)
	policy := EffectiveSelectionPolicy{
		DisabledEngines: append([]string(nil), selection.DisabledEngines...),
		DisabledTargets: append([]string(nil), selection.DisabledTargets...),
		MasterEffort:    selection.MasterEffort,
		WorkerEffort:    selection.WorkerEffort,
	}

	var err error
	if policy.MasterCandidates, err = resolveSelectionCandidates(selection.MasterCandidates, defaults.MasterCandidates, defaultsErr); err != nil {
		return EffectiveSelectionPolicy{}, err
	}
	if policy.WorkerCandidates, err = resolveSelectionCandidates(selection.WorkerCandidates, defaults.WorkerCandidates, defaultsErr); err != nil {
		return EffectiveSelectionPolicy{}, err
	}
	if policy.MasterEffort == "" && defaultsErr == nil {
		policy.MasterEffort = defaults.MasterEffort
	}
	if policy.WorkerEffort == "" && defaultsErr == nil {
		policy.WorkerEffort = defaults.WorkerEffort
	}

	disabledEngines := make(map[string]bool, len(policy.DisabledEngines))
	for _, engine := range policy.DisabledEngines {
		disabledEngines[engine] = true
	}
	disabledTargets := make(map[string]bool, len(policy.DisabledTargets))
	for _, target := range policy.DisabledTargets {
		disabledTargets[target] = true
	}

	policy.MasterCandidates = filterUsableSelectionCandidates(policy.MasterCandidates, disabledEngines, disabledTargets, availability)
	policy.WorkerCandidates = filterUsableSelectionCandidates(policy.WorkerCandidates, disabledEngines, disabledTargets, availability)

	if len(policy.MasterCandidates) == 0 {
		return EffectiveSelectionPolicy{}, fmt.Errorf("selection.master_candidates has no usable candidates after availability and disabled-target filtering")
	}
	if len(policy.WorkerCandidates) == 0 {
		return EffectiveSelectionPolicy{}, fmt.Errorf("selection.worker_candidates has no usable candidates after availability and disabled-target filtering")
	}
	return policy, nil
}

func resolveSelectionCandidates(explicit []string, defaults []string, defaultsErr error) ([]string, error) {
	if len(explicit) > 0 {
		return append([]string(nil), explicit...), nil
	}
	if defaultsErr != nil {
		return nil, defaultsErr
	}
	return append([]string(nil), defaults...), nil
}

func builtinSelectionDefaults(availability map[string]bool) (SelectionConfig, error) {
	hasCodex := availability["codex"]
	hasClaude := availability["claude-code"]
	switch {
	case hasCodex && hasClaude:
		return SelectionConfig{
			MasterCandidates: []string{"codex/gpt-5.4", "claude-code/opus"},
			WorkerCandidates: []string{"codex/gpt-5.4", "claude-code/opus", "codex/gpt-5.4-mini"},
			MasterEffort:     EffortHigh,
			WorkerEffort:     EffortMedium,
		}, nil
	case hasCodex:
		return SelectionConfig{
			MasterCandidates: []string{"codex/gpt-5.4"},
			WorkerCandidates: []string{"codex/gpt-5.4", "codex/gpt-5.4-mini"},
			MasterEffort:     EffortHigh,
			WorkerEffort:     EffortMedium,
		}, nil
	case hasClaude:
		return SelectionConfig{
			MasterCandidates: []string{"claude-code/opus"},
			WorkerCandidates: []string{"claude-code/opus"},
			MasterEffort:     EffortHigh,
			WorkerEffort:     EffortHigh,
		}, nil
	default:
		return SelectionConfig{}, fmt.Errorf("no supported engines found in PATH; install claude or codex")
	}
}

func filterUsableSelectionCandidates(candidates []string, disabledEngines, disabledTargets, availability map[string]bool) []string {
	if len(candidates) == 0 {
		return nil
	}
	filtered := make([]string, 0, len(candidates))
	for _, candidate := range candidates {
		target, err := parseSelectionTarget(candidate, "candidate")
		if err != nil {
			continue
		}
		if disabledEngines[target.Engine] || disabledTargets[candidate] {
			continue
		}
		if !availability[target.Engine] {
			continue
		}
		filtered = append(filtered, candidate)
	}
	if len(filtered) == 0 {
		return nil
	}
	return filtered
}

func compileConfigSelectionPolicy(cfg *Config) EffectiveSelectionPolicy {
	if cfg == nil {
		return EffectiveSelectionPolicy{}
	}
	policy := EffectiveSelectionPolicy{
		MasterEffort: cfg.Master.Effort,
		WorkerEffort: workerRoleDefaults(cfg).Effort,
	}
	appendUniqueSelectionTarget(&policy.MasterCandidates, cfg.Master.Engine, cfg.Master.Model)
	worker := workerRoleDefaults(cfg)
	appendUniqueSelectionTarget(&policy.WorkerCandidates, worker.Engine, worker.Model)
	return policy
}

func hasConfiguredSelectionTargets(cfg *Config) bool {
	if cfg == nil {
		return false
	}
	return (strings.TrimSpace(cfg.Master.Engine) != "" && strings.TrimSpace(cfg.Master.Model) != "") ||
		(strings.TrimSpace(workerRoleDefaults(cfg).Engine) != "" && strings.TrimSpace(workerRoleDefaults(cfg).Model) != "")
}

func appendUniqueSelectionTarget(targets *[]string, engine, model string) {
	if targets == nil {
		return
	}
	engine = strings.TrimSpace(engine)
	model = strings.TrimSpace(model)
	if engine == "" || model == "" {
		return
	}
	candidate := engine + "/" + model
	for _, existing := range *targets {
		if existing == candidate {
			return
		}
	}
	*targets = append(*targets, candidate)
}

func applyEffectiveSelectionPolicy(cfg *Config, policy EffectiveSelectionPolicy) {
	if cfg == nil {
		return
	}
	if target, ok := firstSelectionTarget(policy.MasterCandidates); ok {
		cfg.Master.Engine = target.Engine
		cfg.Master.Model = target.Model
	}
	if policy.MasterEffort != "" {
		cfg.Master.Effort = policy.MasterEffort
	}
	if target, ok := firstSelectionTarget(policy.WorkerCandidates); ok {
		cfg.Roles.Worker.Engine = target.Engine
		cfg.Roles.Worker.Model = target.Model
	}
	if policy.WorkerEffort != "" {
		cfg.Roles.Worker.Effort = policy.WorkerEffort
	}
}

func firstSelectionTarget(candidates []string) (SelectionTarget, bool) {
	if len(candidates) == 0 {
		return SelectionTarget{}, false
	}
	target, err := parseSelectionTarget(candidates[0], "candidate")
	if err != nil {
		return SelectionTarget{}, false
	}
	return target, true
}
