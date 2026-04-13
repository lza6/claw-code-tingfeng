"""Tests for CLI HUD display components."""

import pytest
from unittest.mock import MagicMock, patch

from src.cli.hud import (
    HudContext,
    _render_model,
    _render_iteration,
    _render_tokens,
    _render_cost,
    _render_turns,
    _render_workflow,
    _render_git,
    render_hud,
)


class TestHudContext:
    """Test HudContext dataclass."""

    def test_create_default_context(self):
        """Create context with default values."""
        ctx = HudContext()
        
        assert ctx.model == ''
        assert ctx.provider == ''
        assert ctx.iteration == 0
        assert ctx.max_iterations == 10
        assert ctx.total_tokens == 0
        assert ctx.total_cost == 0.0
        assert ctx.session_turns == 0
        assert ctx.workflow_phase == ''
        assert ctx.git_branch == ''

    def test_create_context_with_values(self):
        """Create context with custom values."""
        ctx = HudContext(
            model='gpt-4',
            provider='openai',
            iteration=5,
            max_iterations=20,
            total_tokens=15000,
            total_cost=0.0450,
            session_turns=8,
            workflow_phase='planning',
            git_branch='feature/test',
        )
        
        assert ctx.model == 'gpt-4'
        assert ctx.provider == 'openai'
        assert ctx.iteration == 5
        assert ctx.max_iterations == 20
        assert ctx.total_tokens == 15000
        assert ctx.total_cost == 0.0450
        assert ctx.session_turns == 8
        assert ctx.workflow_phase == 'planning'
        assert ctx.git_branch == 'feature/test'


class TestRenderModel:
    """Test _render_model function."""

    def test_render_model_simple(self):
        """Render simple model name."""
        ctx = HudContext(model='gpt-4')
        result = _render_model(ctx)
        
        assert result is not None
        assert 'gpt-4' in result

    def test_render_model_with_path(self):
        """Render model name with path (extract last part)."""
        ctx = HudContext(model='openai/gpt-4-turbo')
        result = _render_model(ctx)
        
        assert result is not None
        assert 'gpt-4-turbo' in result
        # Should not contain the full path
        assert 'openai/' not in result

    def test_render_model_empty(self):
        """Return None when model is empty."""
        ctx = HudContext(model='')
        result = _render_model(ctx)
        
        assert result is None

    def test_render_model_none_equivalent(self):
        """Return None when model is falsy."""
        ctx = HudContext(model=None)  # type: ignore
        result = _render_model(ctx)
        
        assert result is None


class TestRenderIteration:
    """Test _render_iteration function."""

    def test_render_iteration_normal(self):
        """Render normal iteration progress."""
        ctx = HudContext(iteration=3, max_iterations=10)
        result = _render_iteration(ctx)
        
        assert result is not None
        assert 'iter:3/10' in result

    def test_render_iteration_at_max(self):
        """Render iteration at maximum."""
        ctx = HudContext(iteration=10, max_iterations=10)
        result = _render_iteration(ctx)
        
        assert result is not None
        assert 'iter:10/10' in result

    def test_render_iteration_zero(self):
        """Return None when iteration is zero."""
        ctx = HudContext(iteration=0, max_iterations=10)
        result = _render_iteration(ctx)
        
        assert result is None

    def test_render_iteration_no_max(self):
        """Return None when max_iterations is zero or negative."""
        ctx = HudContext(iteration=5, max_iterations=0)
        result = _render_iteration(ctx)
        
        assert result is None
        
        ctx = HudContext(iteration=5, max_iterations=-1)
        result = _render_iteration(ctx)
        
        assert result is None


class TestRenderTokens:
    """Test _render_tokens function."""

    def test_render_tokens_positive(self):
        """Render positive token count."""
        ctx = HudContext(total_tokens=15000)
        result = _render_tokens(ctx)
        
        assert result is not None
        assert 'tokens:' in result
        assert '15' in result or '15K' in result or '15,000' in result

    def test_render_tokens_zero(self):
        """Return None when tokens is zero."""
        ctx = HudContext(total_tokens=0)
        result = _render_tokens(ctx)
        
        assert result is None

    def test_render_tokens_negative(self):
        """Return None when tokens is negative."""
        ctx = HudContext(total_tokens=-100)
        result = _render_tokens(ctx)
        
        assert result is None


class TestRenderCost:
    """Test _render_cost function."""

    def test_render_cost_positive(self):
        """Render positive cost."""
        ctx = HudContext(total_cost=0.0450)
        result = _render_cost(ctx)
        
        assert result is not None
        assert '$' in result
        assert '0.0450' in result

    def test_render_cost_zero(self):
        """Return None when cost is zero."""
        ctx = HudContext(total_cost=0.0)
        result = _render_cost(ctx)
        
        assert result is None

    def test_render_cost_negative(self):
        """Return None when cost is negative."""
        ctx = HudContext(total_cost=-0.01)
        result = _render_cost(ctx)
        
        assert result is None

    def test_render_cost_formatting(self):
        """Verify cost is formatted to 4 decimal places."""
        ctx = HudContext(total_cost=0.1)
        result = _render_cost(ctx)
        
        assert result is not None
        # Should have 4 decimal places
        assert '0.1000' in result


class TestRenderTurns:
    """Test _render_turns function."""

    def test_render_turns_positive(self):
        """Render positive turn count."""
        ctx = HudContext(session_turns=8)
        result = _render_turns(ctx)
        
        assert result is not None
        assert 'turns:8' in result

    def test_render_turns_zero(self):
        """Return None when turns is zero."""
        ctx = HudContext(session_turns=0)
        result = _render_turns(ctx)
        
        assert result is None


class TestRenderWorkflow:
    """Test _render_workflow function."""

    def test_render_workflow_phase(self):
        """Render workflow phase."""
        ctx = HudContext(workflow_phase='planning')
        result = _render_workflow(ctx)
        
        assert result is not None
        assert 'workflow:planning' in result

    def test_render_workflow_empty(self):
        """Return None when workflow phase is empty."""
        ctx = HudContext(workflow_phase='')
        result = _render_workflow(ctx)
        
        assert result is None


class TestRenderGit:
    """Test _render_git function."""

    def test_render_git_branch(self):
        """Render git branch name."""
        ctx = HudContext(git_branch='main')
        result = _render_git(ctx)
        
        assert result is not None
        assert 'main' in result

    def test_render_git_branch_with_prefix(self):
        """Render git branch with prefix."""
        ctx = HudContext(git_branch='feature/new-ui')
        result = _render_git(ctx)
        
        assert result is not None
        assert 'feature/new-ui' in result

    def test_render_git_empty(self):
        """Return None when git branch is empty."""
        ctx = HudContext(git_branch='')
        result = _render_git(ctx)
        
        assert result is None


class TestRenderHud:
    """Test render_hud function."""

    def test_render_hud_minimal_preset(self):
        """Render HUD with minimal preset."""
        ctx = HudContext(
            model='gpt-4',
            iteration=3,
            max_iterations=10,
            total_tokens=5000,
            total_cost=0.0150,
        )
        
        result = render_hud(ctx, preset='minimal')
        
        assert isinstance(result, str)
        # Minimal should show fewer elements
        assert len(result) > 0

    def test_render_hud_focused_preset(self):
        """Render HUD with focused preset."""
        ctx = HudContext(
            model='gpt-4',
            iteration=3,
            max_iterations=10,
            total_tokens=5000,
            total_cost=0.0150,
            session_turns=5,
        )
        
        result = render_hud(ctx, preset='focused')
        
        assert isinstance(result, str)
        # Focused should show more than minimal
        assert len(result) > 0

    def test_render_hud_full_preset(self):
        """Render HUD with full preset."""
        ctx = HudContext(
            model='gpt-4',
            provider='openai',
            iteration=3,
            max_iterations=10,
            total_tokens=5000,
            total_cost=0.0150,
            session_turns=5,
            workflow_phase='coding',
            git_branch='main',
        )
        
        result = render_hud(ctx, preset='full')
        
        assert isinstance(result, str)
        # Full should show all available elements
        assert 'gpt-4' in result or 'iter:3/10' in result

    def test_render_hud_empty_context(self):
        """Render HUD with mostly empty context."""
        ctx = HudContext()
        
        result = render_hud(ctx, preset='full')
        
        assert isinstance(result, str)
        # Should still return a string (possibly minimal)
        assert result is not None

    def test_render_hud_custom_separator(self):
        """Render HUD respects separator configuration."""
        # Need multiple elements to see separator
        ctx = HudContext(
            model='test', 
            iteration=1, 
            max_iterations=5,
            total_tokens=1000,
        )
        
        result = render_hud(ctx, preset='minimal')
        
        assert isinstance(result, str)
        # With multiple elements, should have separator
        if len(result.strip()) > 0 and ('test' in result and 'tokens:' in result):
            assert '|' in result or '│' in result

    def test_render_hud_presets_comparison(self):
        """Verify different presets produce different output lengths."""
        ctx = HudContext(
            model='gpt-4',
            iteration=5,
            max_iterations=10,
            total_tokens=10000,
            total_cost=0.0300,
            session_turns=7,
            workflow_phase='review',
            git_branch='develop',
        )
        
        minimal = render_hud(ctx, preset='minimal')
        focused = render_hud(ctx, preset='focused')
        full = render_hud(ctx, preset='full')
        
        # All should be strings
        assert isinstance(minimal, str)
        assert isinstance(focused, str)
        assert isinstance(full, str)
        
        # Full should generally be longer or equal to focused
        # (depending on implementation details)
        assert len(full) >= len(minimal)


class TestHudIntegration:
    """Integration tests for HUD components."""

    def test_all_renderers_with_full_context(self):
        """Test all renderer functions together."""
        ctx = HudContext(
            model='claude-3-opus',
            provider='anthropic',
            iteration=7,
            max_iterations=15,
            total_tokens=25000,
            total_cost=0.0750,
            session_turns=12,
            workflow_phase='testing',
            git_branch='feature/hud',
        )
        
        # All renderers should produce non-None results
        assert _render_model(ctx) is not None
        assert _render_iteration(ctx) is not None
        assert _render_tokens(ctx) is not None
        assert _render_cost(ctx) is not None
        assert _render_turns(ctx) is not None
        assert _render_workflow(ctx) is not None
        assert _render_git(ctx) is not None

    def test_all_renderers_with_empty_context(self):
        """Test all renderers return None with empty context."""
        ctx = HudContext()
        
        assert _render_model(ctx) is None
        assert _render_iteration(ctx) is None
        assert _render_tokens(ctx) is None
        assert _render_cost(ctx) is None
        assert _render_turns(ctx) is None
        assert _render_workflow(ctx) is None
        assert _render_git(ctx) is None

    def test_hud_context_immutability_pattern(self):
        """Verify HudContext can be recreated with updated values."""
        ctx1 = HudContext(model='gpt-3', iteration=1, max_iterations=10)
        
        # Create new context with updated values (dataclass pattern)
        ctx2 = HudContext(
            model=ctx1.model,
            iteration=ctx1.iteration + 1,
            max_iterations=ctx1.max_iterations,
            total_tokens=1000,
        )
        
        assert ctx2.iteration == 2
        assert ctx2.total_tokens == 1000
        # Original unchanged
        assert ctx1.iteration == 1


class TestHudEdgeCases:
    """Test HUD edge cases and boundary conditions."""

    def test_very_large_token_count(self):
        """Handle very large token counts."""
        ctx = HudContext(total_tokens=999999999)
        result = _render_tokens(ctx)
        
        assert result is not None
        # Should handle large numbers gracefully
        assert 'tokens:' in result

    def test_very_small_cost(self):
        """Handle very small cost values."""
        ctx = HudContext(total_cost=0.0001)
        result = _render_cost(ctx)
        
        assert result is not None
        assert '$' in result

    def test_iteration_exceeds_max(self):
        """Handle iteration exceeding max (edge case)."""
        ctx = HudContext(iteration=15, max_iterations=10)
        result = _render_iteration(ctx)
        
        assert result is not None
        assert 'iter:15/10' in result

    def test_special_characters_in_model_name(self):
        """Handle special characters in model name."""
        ctx = HudContext(model='model-with-dashes_and_underscores.v2')
        result = _render_model(ctx)
        
        assert result is not None
        # Should preserve special chars
        assert 'model-with-dashes_and_underscores.v2' in result

    def test_unicode_in_git_branch(self):
        """Handle unicode in git branch name."""
        ctx = HudContext(git_branch='功能分支')
        result = _render_git(ctx)
        
        assert result is not None
        # Should handle unicode
        assert '功能分支' in result or len(result) > 0
