package cli

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"
)

type CompiledProtocolComposition struct {
	Version            int                         `json:"version"`
	CompiledAt         string                      `json:"compiled_at,omitempty"`
	CompilerVersion    string                      `json:"compiler_version,omitempty"`
	Philosophy         []string                    `json:"philosophy,omitempty"`
	BehaviorContract   []string                    `json:"behavior_contract,omitempty"`
	RequiredRoles      []string                    `json:"required_roles,omitempty"`
	RequiredGates      []string                    `json:"required_gates,omitempty"`
	RequiredProofKinds []string                    `json:"required_proof_kinds,omitempty"`
	SourceSlots        []ProtocolCompositionSlot   `json:"source_slots,omitempty"`
	OutputSources      []ProtocolCompositionOutput `json:"output_sources,omitempty"`
	SelectedPriorRefs  []string                    `json:"selected_prior_refs,omitempty"`
}

func ProtocolCompositionPath(runDir string) string {
	return filepath.Join(runDir, "protocol-composition.json")
}

func LoadCompiledProtocolComposition(path string) (*CompiledProtocolComposition, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}
	state, err := parseCompiledProtocolComposition(data)
	if err != nil {
		return nil, fmt.Errorf("parse protocol composition: %w", err)
	}
	return state, nil
}

func SaveCompiledProtocolComposition(path string, state *CompiledProtocolComposition) error {
	if state == nil {
		return fmt.Errorf("protocol composition is nil")
	}
	if err := validateCompiledProtocolComposition(state); err != nil {
		return err
	}
	normalizeCompiledProtocolComposition(state)
	if state.CompiledAt == "" {
		state.CompiledAt = time.Now().UTC().Format(time.RFC3339)
	}
	data, err := json.MarshalIndent(state, "", "  ")
	if err != nil {
		return err
	}
	return writeFileAtomic(path, data, 0o644)
}

func parseCompiledProtocolComposition(data []byte) (*CompiledProtocolComposition, error) {
	var state CompiledProtocolComposition
	if len(strings.TrimSpace(string(data))) == 0 {
		return nil, durableSchemaHintError(DurableSurfaceProtocolComposition, fmt.Errorf("protocol composition is empty"))
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&state); err != nil {
		return nil, durableSchemaHintError(DurableSurfaceProtocolComposition, err)
	}
	if err := ensureJSONEOF(decoder); err != nil {
		return nil, durableSchemaHintError(DurableSurfaceProtocolComposition, err)
	}
	if err := validateCompiledProtocolComposition(&state); err != nil {
		return nil, durableSchemaHintError(DurableSurfaceProtocolComposition, err)
	}
	normalizeCompiledProtocolComposition(&state)
	return &state, nil
}

func validateCompiledProtocolComposition(state *CompiledProtocolComposition) error {
	if state == nil {
		return fmt.Errorf("protocol composition is nil")
	}
	if state.Version <= 0 {
		return fmt.Errorf("protocol composition version must be positive")
	}
	for _, slot := range state.SourceSlots {
		if !isValidCompilerInputSlot(slot.Slot) {
			return fmt.Errorf("protocol composition slot %q is invalid", slot.Slot)
		}
		if len(compactStrings(slot.Refs)) == 0 {
			return fmt.Errorf("protocol composition slot %q refs are required", slot.Slot)
		}
	}
	for _, output := range state.OutputSources {
		if strings.TrimSpace(output.Output) == "" {
			return fmt.Errorf("protocol composition output_sources output is required")
		}
		if !isValidCompilerInputSlot(output.SourceSlot) {
			return fmt.Errorf("protocol composition output_sources source_slot %q is invalid", output.SourceSlot)
		}
	}
	return nil
}

func normalizeCompiledProtocolComposition(state *CompiledProtocolComposition) {
	if state.Version <= 0 {
		state.Version = 1
	}
	state.CompiledAt = strings.TrimSpace(state.CompiledAt)
	state.CompilerVersion = strings.TrimSpace(state.CompilerVersion)
	state.Philosophy = compactStrings(state.Philosophy)
	state.BehaviorContract = compactStrings(state.BehaviorContract)
	state.RequiredRoles = compactStrings(state.RequiredRoles)
	state.RequiredGates = compactStrings(state.RequiredGates)
	state.RequiredProofKinds = compactStrings(state.RequiredProofKinds)
	state.SelectedPriorRefs = compactStrings(state.SelectedPriorRefs)
	if state.SourceSlots == nil {
		state.SourceSlots = []ProtocolCompositionSlot{}
	}
	for i := range state.SourceSlots {
		state.SourceSlots[i].Slot = strings.TrimSpace(state.SourceSlots[i].Slot)
		state.SourceSlots[i].Refs = compactStrings(state.SourceSlots[i].Refs)
	}
	if state.OutputSources == nil {
		state.OutputSources = []ProtocolCompositionOutput{}
	}
	for i := range state.OutputSources {
		state.OutputSources[i].Output = strings.TrimSpace(state.OutputSources[i].Output)
		state.OutputSources[i].SourceSlot = strings.TrimSpace(state.OutputSources[i].SourceSlot)
		state.OutputSources[i].Refs = compactStrings(state.OutputSources[i].Refs)
	}
}

func protocolCompositionView(state *CompiledProtocolComposition) ProtocolComposition {
	if state == nil {
		return ProtocolComposition{}
	}
	return normalizeProtocolComposition(ProtocolComposition{
		Enabled:            true,
		Philosophy:         append([]string(nil), state.Philosophy...),
		BehaviorContract:   append([]string(nil), state.BehaviorContract...),
		RequiredRoles:      append([]string(nil), state.RequiredRoles...),
		RequiredGates:      append([]string(nil), state.RequiredGates...),
		RequiredProofKinds: append([]string(nil), state.RequiredProofKinds...),
		SourceSlots:        append([]ProtocolCompositionSlot(nil), state.SourceSlots...),
		OutputSources:      append([]ProtocolCompositionOutput(nil), state.OutputSources...),
		SelectedPriorRefs:  append([]string(nil), state.SelectedPriorRefs...),
	})
}
