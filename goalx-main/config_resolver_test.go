package goalx

import (
	"strings"
	"testing"
)

type resolverTestLayers struct {
	Base        Config
	ManualDraft *Config
}

type resolverTestRequest struct {
	Mode         Mode
	MasterEngine string
	MasterModel  string
}

func resolverTestEngineCatalog(available bool) map[string]EngineConfig {
	engines := copyEngines(BuiltinEngines)
	for name, engine := range engines {
		if available {
			engine.Command = "sh -c true"
		} else {
			engine.Command = "goalx-missing-" + name + " {model_id}"
		}
		engines[name] = engine
	}
	return engines
}

func resolveConfigFixture(layers resolverTestLayers, req resolverTestRequest) (*ResolvedConfig, error) {
	base := BuiltinDefaults
	mergeConfig(&base, &layers.Base)
	attachDimensionCatalog(&base, copyStringCatalog(BuiltinDimensions))
	return resolveConfigWithOptions(&ConfigLayers{
		Config:     base,
		Engines:    resolverTestEngineCatalog(true),
		Dimensions: copyStringCatalog(BuiltinDimensions),
	}, ResolveRequest{
		ManualDraft: layers.ManualDraft,
		Mode:        req.Mode,
		MasterOverride: &MasterConfig{
			Engine: req.MasterEngine,
			Model:  req.MasterModel,
		},
	}, true)
}

func TestResolveConfigSemantics(t *testing.T) {
	t.Parallel()

	t.Run("explicit selection policy wins over implicit defaults", func(t *testing.T) {
		resolved, err := resolveConfigFixture(resolverTestLayers{
			Base: Config{
				Name:      "demo",
				Mode:      ModeWorker,
				Objective: "lock config state",
				Selection: SelectionConfig{
					MasterCandidates: []string{"claude-code/opus"},
					WorkerCandidates: []string{"codex/gpt-5.4-mini"},
				},
				Target:          TargetConfig{Files: []string{"README.md"}},
				LocalValidation: LocalValidationConfig{Command: "go test ./..."},
			},
		}, resolverTestRequest{Mode: ModeWorker})
		if err != nil {
			t.Fatalf("resolveConfigFixture: %v", err)
		}
		if resolved.Config.Master.Engine != "claude-code" || resolved.Config.Master.Model != "opus" {
			t.Fatalf("master = %#v, want claude-code/opus", resolved.Config.Master)
		}
		if resolved.Config.Roles.Worker.Engine != "codex" || resolved.Config.Roles.Worker.Model != "gpt-5.4-mini" {
			t.Fatalf("develop = %#v, want codex/gpt-5.4-mini", resolved.Config.Roles.Worker)
		}
	})

	t.Run("manual draft override beats base defaults", func(t *testing.T) {
		resolved, err := resolveConfigFixture(resolverTestLayers{
			Base: Config{
				Name:            "demo",
				Mode:            ModeWorker,
				Objective:       "lock config state",
				Target:          TargetConfig{Files: []string{"README.md"}},
				LocalValidation: LocalValidationConfig{Command: "go test ./..."},
			},
			ManualDraft: &Config{
				Master: MasterConfig{Engine: "claude-code", Model: "opus"},
			},
		}, resolverTestRequest{Mode: ModeWorker})
		if err != nil {
			t.Fatalf("resolveConfigFixture: %v", err)
		}
		if resolved.Config.Master.Engine != "claude-code" || resolved.Config.Master.Model != "opus" {
			t.Fatalf("master = %#v, want manual draft claude-code/opus", resolved.Config.Master)
		}
	})

	t.Run("cli override beats manual draft", func(t *testing.T) {
		resolved, err := resolveConfigFixture(resolverTestLayers{
			Base: Config{
				Name:            "demo",
				Mode:            ModeWorker,
				Objective:       "lock config state",
				Target:          TargetConfig{Files: []string{"README.md"}},
				LocalValidation: LocalValidationConfig{Command: "go test ./..."},
			},
			ManualDraft: &Config{
				Master: MasterConfig{Engine: "claude-code", Model: "opus"},
			},
		}, resolverTestRequest{
			Mode:         ModeWorker,
			MasterEngine: "codex",
			MasterModel:  "gpt-5.4",
		})
		if err != nil {
			t.Fatalf("resolveConfigFixture: %v", err)
		}
		if resolved.Config.Master.Engine != "codex" || resolved.Config.Master.Model != "gpt-5.4" {
			t.Fatalf("master = %#v, want cli override codex/gpt-5.4", resolved.Config.Master)
		}
	})
}

func TestResolveConfigReturnsErrorWhenNoEngineCanBeSelected(t *testing.T) {
	t.Parallel()

	base := Config{
		Name:            "demo",
		Mode:            ModeWorker,
		Objective:       "ship it",
		Target:          TargetConfig{Files: []string{"README.md"}},
		LocalValidation: LocalValidationConfig{Command: "go test ./..."},
	}
	merged := BuiltinDefaults
	mergeConfig(&merged, &base)
	attachDimensionCatalog(&merged, copyStringCatalog(BuiltinDimensions))

	_, err := resolveConfigWithOptions(&ConfigLayers{
		Config:     merged,
		Engines:    resolverTestEngineCatalog(false),
		Dimensions: copyStringCatalog(BuiltinDimensions),
	}, ResolveRequest{}, true)
	if err == nil || !strings.Contains(err.Error(), "no supported engines found in PATH") {
		t.Fatalf("resolveConfigWithOptions error = %v, want no supported engines", err)
	}
}

func TestResolveConfigResolverUsesImplicitSelectionDefaults(t *testing.T) {
	t.Parallel()

	base := BuiltinDefaults
	base.Name = "demo"
	base.Mode = ModeAuto
	base.Objective = "lock config state"
	base.Target = TargetConfig{Files: []string{"README.md"}}
	base.LocalValidation = LocalValidationConfig{Command: "go test ./..."}
	attachDimensionCatalog(&base, copyStringCatalog(BuiltinDimensions))

	resolved, err := resolveConfigWithOptions(&ConfigLayers{
		Config:     base,
		Engines:    resolverTestEngineCatalog(true),
		Dimensions: copyStringCatalog(BuiltinDimensions),
	}, ResolveRequest{}, true)
	if err != nil {
		t.Fatalf("resolveConfigWithOptions: %v", err)
	}

	if resolved.Config.Master.Engine != "codex" || resolved.Config.Master.Model != "gpt-5.4" {
		t.Fatalf("master = %#v, want codex/gpt-5.4", resolved.Config.Master)
	}
	if got := resolved.Config.Preferences.Worker.Guidance; got != "默认 gpt-5.4 medium。复杂分析、架构分歧或高风险收口可升到 high 或改用 opus；轻量切片用 fast。" {
		t.Fatalf("worker guidance = %q", got)
	}
	if got := resolved.SelectionPolicy.MasterCandidates[0]; got != "codex/gpt-5.4" {
		t.Fatalf("master candidate = %q, want codex/gpt-5.4", got)
	}
}
