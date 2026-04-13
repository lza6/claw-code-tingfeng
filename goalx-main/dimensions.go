package goalx

import (
	"fmt"
	"strings"
)

const (
	DimensionSourceBuiltin = "builtin"
	DimensionSourceConfig  = "config"
	DimensionSourceInline  = "inline"
)

// BuiltinDimensions are named goal dimensions for session guidance.
var BuiltinDimensions = map[string]string{
	"depth":         "Depth: Pick the single most impactful area and go as deep as possible. Trace code paths end-to-end. Prefer one thoroughly verified finding over five shallow ones.",
	"breadth":       "Breadth: Scan all dimensions to build a complete map. Cover every major component. Find blind spots and unexpected connections.",
	"creative":      "Creative: Think beyond conventional approaches. Propose non-obvious solutions. Challenge assumptions about what's possible. Look for elegant simplifications.",
	"feasibility":   "Feasibility: For every proposal, assess implementation cost, risk, dependencies, and timeline. Separate easy wins from heavy lifts. Be concrete about effort.",
	"adversarial":   "Adversarial: Your job is to find problems. Look for bugs, design flaws, edge cases, and incorrect assumptions. If something looks fine, try harder to break it.",
	"audit":         "Audit: Conduct a systematic review of correctness, regressions, safety, operational impact, and documentation consistency. Treat the whole change as a production system, not just a code diff.",
	"evidence":      "Evidence: Quantify everything. Run benchmarks, measure build times, count lines/functions/dependencies, check test coverage. No opinions without data.",
	"perfectionist": "Perfectionist: Demand ironclad evidence for every claim. Cite exact code references. Prefer fewer high-quality findings over many shallow ones. Re-read before commit. Depth over breadth.",
	"comparative":   "Comparative: Compare with industry best practices, similar projects, and established patterns. Identify where deviations are intentional strengths or accidental weaknesses.",
	"user":          "User perspective: Think from the end user's point of view. What's the experience like? What's confusing? What's missing? Focus on usability and developer ergonomics.",
}

// ResolvedDimension is one fully resolved dimension attached to a session.
type ResolvedDimension struct {
	Name     string `json:"name" yaml:"name"`
	Guidance string `json:"guidance" yaml:"guidance"`
	Source   string `json:"source,omitempty" yaml:"source,omitempty"`
}

// ResolveDimensionSpecs resolves dimension specs against the built-in catalog plus any
// additional custom catalogs. Bare names resolve from the catalog; "name=guidance"
// creates an inline dimension.
func ResolveDimensionSpecs(names []string, custom ...map[string]string) ([]ResolvedDimension, error) {
	return resolveDimensionSpecsWithCatalog(BuiltinDimensions, names, custom...)
}

func resolveDimensionSpecsWithCatalog(base map[string]string, names []string, custom ...map[string]string) ([]ResolvedDimension, error) {
	catalog := copyStringCatalog(base)
	builtin := make(map[string]bool, len(base))
	for name := range base {
		builtin[name] = true
	}
	for _, m := range custom {
		for name, guidance := range m {
			name = strings.TrimSpace(name)
			if name == "" || builtin[name] {
				continue
			}
			catalog[name] = strings.TrimSpace(guidance)
		}
	}

	specs := make([]ResolvedDimension, 0, len(names))
	for _, raw := range names {
		raw = strings.TrimSpace(raw)
		if raw == "" {
			continue
		}
		if name, guidance, ok, err := parseInlineDimension(raw); err != nil {
			return nil, err
		} else if ok {
			specs = append(specs, ResolvedDimension{
				Name:     name,
				Guidance: guidance,
				Source:   DimensionSourceInline,
			})
			continue
		}

		guidance, ok := catalog[raw]
		if !ok {
			return nil, fmt.Errorf("unknown dimension %q", raw)
		}
		source := DimensionSourceConfig
		if builtin[raw] {
			source = DimensionSourceBuiltin
		}
		specs = append(specs, ResolvedDimension{
			Name:     raw,
			Guidance: guidance,
			Source:   source,
		})
	}
	return specs, nil
}

func parseInlineDimension(raw string) (string, string, bool, error) {
	name, guidance, ok := strings.Cut(raw, "=")
	if !ok {
		return "", "", false, nil
	}
	name = strings.TrimSpace(name)
	guidance = strings.TrimSpace(guidance)
	if name == "" {
		return "", "", false, fmt.Errorf("invalid inline dimension %q: missing name", raw)
	}
	if guidance == "" {
		return "", "", false, fmt.Errorf("invalid inline dimension %q: missing guidance", raw)
	}
	return name, guidance, true, nil
}

func ResolveDimensionNames(specs []ResolvedDimension) []string {
	if len(specs) == 0 {
		return nil
	}
	names := make([]string, 0, len(specs))
	for _, spec := range specs {
		if strings.TrimSpace(spec.Name) == "" {
			continue
		}
		names = append(names, spec.Name)
	}
	return names
}
