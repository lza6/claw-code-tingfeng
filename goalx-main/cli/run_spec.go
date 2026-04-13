package cli

import (
	"fmt"
	"path/filepath"

	goalx "github.com/vonbai/goalx"
	"gopkg.in/yaml.v3"
)

func RunSpecPath(runDir string) string {
	return filepath.Join(runDir, "run-spec.yaml")
}

func LoadRunSpec(runDir string) (*goalx.Config, error) {
	cfg, err := goalx.LoadYAML[goalx.Config](RunSpecPath(runDir))
	if err != nil {
		return nil, fmt.Errorf("load run spec: %w", err)
	}
	if cfg.Name == "" {
		return nil, fmt.Errorf("run spec missing at %s", RunSpecPath(runDir))
	}
	return &cfg, nil
}

func SaveRunSpec(runDir string, cfg *goalx.Config) error {
	if cfg == nil {
		return fmt.Errorf("run spec config is nil")
	}
	data, err := yaml.Marshal(cfg)
	if err != nil {
		return fmt.Errorf("marshal run spec: %w", err)
	}
	if err := writeFileAtomic(RunSpecPath(runDir), data, 0o644); err != nil {
		return fmt.Errorf("write run spec: %w", err)
	}
	return nil
}

func LoadSavedRunSpec(savedRunDir string) (*goalx.Config, error) {
	cfg, err := goalx.LoadYAML[goalx.Config](filepath.Join(savedRunDir, "run-spec.yaml"))
	if err != nil {
		return nil, fmt.Errorf("load saved run spec: %w", err)
	}
	if cfg.Name == "" {
		return nil, fmt.Errorf("saved run spec missing at %s", filepath.Join(savedRunDir, "run-spec.yaml"))
	}
	return &cfg, nil
}
