package cli

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"time"

	goalx "github.com/vonbai/goalx"
)

const dimensionUsage = "usage: goalx dimension [--run NAME] <session-N|all> (--set SPECS | --add SPEC | --remove SPEC)"

type DimensionsState struct {
	Version   int                                  `json:"version"`
	Sessions  map[string][]goalx.ResolvedDimension `json:"sessions,omitempty"`
	UpdatedAt string                               `json:"updated_at,omitempty"`
}

type dimensionMutation struct {
	target string
	action string
	values []string
}

func ControlDimensionsPath(runDir string) string {
	return filepath.Join(ControlDir(runDir), "dimensions.json")
}

func Dimension(projectRoot string, args []string) error {
	runName, rest, err := extractRunFlag(args)
	if err != nil {
		return err
	}
	if printUsageIfHelp(rest, dimensionUsage) {
		return nil
	}

	mutation, err := parseDimensionMutation(rest)
	if err != nil {
		return err
	}

	rc, err := ResolveRun(projectRoot, runName)
	if err != nil {
		return err
	}
	targets, err := resolveDimensionTargets(rc.RunDir, mutation.target, mutation.action)
	if err != nil {
		return err
	}
	catalog, err := loadDimensionCatalog(rc.ProjectRoot)
	if err != nil {
		return fmt.Errorf("load dimension catalog: %w", err)
	}

	state, err := EnsureDimensionsState(rc.RunDir)
	if err != nil {
		return err
	}
	for _, sessionName := range targets {
		next, err := applyDimensionMutation(state.Sessions[sessionName], mutation.action, mutation.values, catalog)
		if err != nil {
			return err
		}
		if len(next) == 0 {
			delete(state.Sessions, sessionName)
			continue
		}
		state.Sessions[sessionName] = next
	}
	if err := SaveDimensionsState(ControlDimensionsPath(rc.RunDir), state); err != nil {
		return err
	}

	for _, sessionName := range targets {
		fmt.Printf("%s: %s\n", sessionName, formatDimensions(state.Sessions[sessionName]))
	}
	return nil
}

func parseDimensionMutation(args []string) (dimensionMutation, error) {
	if len(args) != 3 {
		return dimensionMutation{}, fmt.Errorf(dimensionUsage)
	}

	mutation := dimensionMutation{
		target: strings.TrimSpace(args[0]),
		action: args[1],
	}
	if mutation.target == "" {
		return dimensionMutation{}, fmt.Errorf(dimensionUsage)
	}

	allowEmpty := mutation.action == "--set"
	values, err := parseDimensionSpecs(args[2], allowEmpty)
	if err != nil {
		return dimensionMutation{}, err
	}
	switch mutation.action {
	case "--set":
		mutation.values = values
	case "--add", "--remove":
		if mutation.target == "all" || len(values) != 1 {
			return dimensionMutation{}, fmt.Errorf(dimensionUsage)
		}
		mutation.values = values
	default:
		return dimensionMutation{}, fmt.Errorf(dimensionUsage)
	}
	return mutation, nil
}

func resolveDimensionTargets(runDir, target, action string) ([]string, error) {
	if target == "all" {
		if action != "--set" {
			return nil, fmt.Errorf(dimensionUsage)
		}
		indexes, err := existingSessionIndexes(runDir)
		if err != nil {
			return nil, err
		}
		if len(indexes) == 0 {
			return nil, fmt.Errorf("run has no sessions")
		}
		targets := make([]string, 0, len(indexes))
		for _, idx := range indexes {
			targets = append(targets, SessionName(idx))
		}
		return targets, nil
	}

	idx, err := parseSessionIndex(target)
	if err != nil {
		return nil, err
	}
	ok, err := hasSessionIndex(runDir, idx)
	if err != nil {
		return nil, err
	}
	if !ok {
		return nil, fmt.Errorf("session %q out of range", target)
	}
	return []string{target}, nil
}

func parseDimensionSpecs(raw string, allowEmpty bool) ([]string, error) {
	specs := splitListFlag(raw)
	unique := make([]string, 0, len(specs))
	for _, spec := range specs {
		if !slices.Contains(unique, spec) {
			unique = append(unique, spec)
		}
	}
	if len(unique) == 0 && !allowEmpty {
		return nil, fmt.Errorf(dimensionUsage)
	}
	return unique, nil
}

func applyDimensionMutation(current []goalx.ResolvedDimension, action string, values []string, catalog map[string]string) ([]goalx.ResolvedDimension, error) {
	specs, err := goalx.ResolveDimensionSpecs(values, catalog)
	if err != nil {
		return nil, err
	}
	switch action {
	case "--set":
		return append([]goalx.ResolvedDimension(nil), specs...), nil
	case "--add":
		next := append([]goalx.ResolvedDimension(nil), current...)
		for _, spec := range specs {
			replaced := false
			for i := range next {
				if next[i].Name == spec.Name {
					next[i] = spec
					replaced = true
					break
				}
			}
			if !replaced {
				next = append(next, spec)
			}
		}
		return next, nil
	case "--remove":
		removeNames := make(map[string]bool, len(specs))
		for _, spec := range specs {
			removeNames[spec.Name] = true
		}
		next := make([]goalx.ResolvedDimension, 0, len(current))
		for _, spec := range current {
			if !removeNames[spec.Name] {
				next = append(next, spec)
			}
		}
		return next, nil
	default:
		return append([]goalx.ResolvedDimension(nil), current...), nil
	}
}

func formatDimensions(values []goalx.ResolvedDimension) string {
	if len(values) == 0 {
		return "(none)"
	}
	names := make([]string, 0, len(values))
	for _, value := range values {
		names = append(names, value.Name)
	}
	return strings.Join(names, ",")
}

func LoadDimensionsState(path string) (*DimensionsState, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}

	state := &DimensionsState{}
	if len(strings.TrimSpace(string(data))) == 0 {
		state.Version = 1
		state.Sessions = map[string][]goalx.ResolvedDimension{}
		return state, nil
	}
	if err := json.Unmarshal(data, state); err != nil {
		return nil, fmt.Errorf("parse dimensions state: %w", err)
	}
	normalizeDimensionsState(state)
	return state, nil
}

func SaveDimensionsState(path string, state *DimensionsState) error {
	if state == nil {
		return fmt.Errorf("dimensions state is nil")
	}
	normalizeDimensionsState(state)
	state.UpdatedAt = time.Now().UTC().Format(time.RFC3339)
	return writeJSONFile(path, state)
}

func EnsureDimensionsState(runDir string) (*DimensionsState, error) {
	path := ControlDimensionsPath(runDir)
	state, err := LoadDimensionsState(path)
	if err != nil {
		return nil, err
	}
	created := false
	if state == nil {
		state = &DimensionsState{
			Version:  1,
			Sessions: map[string][]goalx.ResolvedDimension{},
		}
		created = true
	}
	seeded, err := seedDimensionsStateFromIdentity(runDir, state)
	if err != nil {
		return nil, err
	}
	if created || seeded {
		if err := SaveDimensionsState(path, state); err != nil {
			return nil, err
		}
	}
	return state, nil
}

func CurrentSessionDimensions(runDir, sessionName string, fallback []goalx.ResolvedDimension) []goalx.ResolvedDimension {
	state, err := LoadDimensionsState(ControlDimensionsPath(runDir))
	if err == nil && state != nil {
		if current := state.Sessions[sessionName]; len(current) > 0 {
			return append([]goalx.ResolvedDimension(nil), current...)
		}
	}
	return append([]goalx.ResolvedDimension(nil), fallback...)
}

func seedDimensionsStateFromIdentity(runDir string, state *DimensionsState) (bool, error) {
	indexes, err := existingSessionIndexes(runDir)
	if err != nil {
		return false, err
	}
	seeded := false
	for _, idx := range indexes {
		sessionName := SessionName(idx)
		if len(state.Sessions[sessionName]) > 0 {
			continue
		}
		identity, err := LoadSessionIdentity(SessionIdentityPath(runDir, sessionName))
		if err != nil {
			return false, err
		}
		if identity == nil || len(identity.Dimensions) == 0 {
			continue
		}
		state.Sessions[sessionName] = append([]goalx.ResolvedDimension(nil), identity.Dimensions...)
		seeded = true
	}
	return seeded, nil
}

func normalizeDimensionsState(state *DimensionsState) {
	if state.Version == 0 {
		state.Version = 1
	}
	if state.Sessions == nil {
		state.Sessions = map[string][]goalx.ResolvedDimension{}
		return
	}
	for sessionName, values := range state.Sessions {
		normalized := make([]goalx.ResolvedDimension, 0, len(values))
		seen := make(map[string]bool, len(values))
		for _, value := range values {
			value.Name = strings.TrimSpace(value.Name)
			value.Guidance = strings.TrimSpace(value.Guidance)
			value.Source = strings.TrimSpace(value.Source)
			if value.Name == "" || value.Guidance == "" || seen[value.Name] {
				continue
			}
			normalized = append(normalized, value)
			seen[value.Name] = true
		}
		if len(normalized) == 0 {
			delete(state.Sessions, sessionName)
			continue
		}
		state.Sessions[sessionName] = normalized
	}
}
