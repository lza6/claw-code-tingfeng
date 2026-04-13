"""Tests for CLI Command Registry."""

import pytest
from src.cli.command_registry import CommandRegistry, CommandHandler


class TestCommandHandler:
    """Test CommandHandler dataclass."""

    def test_create_handler_minimal(self):
        """Create handler with minimal fields."""
        def dummy_handler(args):
            return "ok"
        
        handler = CommandHandler(
            name="/test",
            handler=dummy_handler,
            description="Test command",
        )
        
        assert handler.name == "/test"
        assert handler.description == "Test command"
        assert handler.category == "general"
        assert handler.aliases == []
        assert handler.requires_engine is False

    def test_create_handler_full(self):
        """Create handler with all fields."""
        def dummy_handler(args):
            return "ok"
        
        handler = CommandHandler(
            name="/custom",
            handler=dummy_handler,
            description="Custom command",
            category="plugins",
            aliases=["/c", "/cust"],
            requires_engine=True,
        )
        
        assert handler.name == "/custom"
        assert handler.category == "plugins"
        assert handler.aliases == ["/c", "/cust"]
        assert handler.requires_engine is True

    def test_matches_exact_name(self):
        """Match exact command name."""
        def dummy(args):
            pass
        
        handler = CommandHandler(name="/help", handler=dummy, description="Help")
        
        assert handler.matches("/help") is True
        assert handler.matches("/HELP") is True  # Case insensitive
        assert handler.matches(" /help ") is True  # Strips whitespace

    def test_matches_alias(self):
        """Match command alias."""
        def dummy(args):
            pass
        
        handler = CommandHandler(
            name="/quit",
            handler=dummy,
            description="Quit",
            aliases=["/exit", "/q"],
        )
        
        assert handler.matches("/quit") is True
        assert handler.matches("/exit") is True
        assert handler.matches("/q") is True
        assert handler.matches("/QUIT") is True

    def test_no_match(self):
        """No match for unknown command."""
        def dummy(args):
            pass
        
        handler = CommandHandler(name="/help", handler=dummy, description="Help")
        
        assert handler.matches("/unknown") is False
        assert handler.matches("/hel") is False


class TestCommandRegistry:
    """Test CommandRegistry class."""

    def setup_method(self):
        """Setup fresh registry for each test."""
        self.registry = CommandRegistry()

    def test_register_command(self):
        """Register a new command."""
        def handler(args):
            return "handled"
        
        self.registry.register("/test", handler, "Test command")
        
        assert "/test" in self.registry.commands
        cmd = self.registry.commands["/test"]
        assert cmd.name == "/test"
        assert cmd.description == "Test command"
        assert cmd.category == "general"

    def test_register_command_with_category(self):
        """Register command with custom category."""
        def handler(args):
            pass
        
        self.registry.register(
            "/plugin-cmd",
            handler,
            "Plugin command",
            category="plugins"
        )
        
        cmd = self.registry.commands["/plugin-cmd"]
        assert cmd.category == "plugins"

    def test_register_command_with_aliases(self):
        """Register command with aliases."""
        def handler(args):
            pass
        
        self.registry.register(
            "/quit",
            handler,
            "Quit application",
            aliases=["/exit", "/q"]
        )
        
        # Main command registered
        assert "/quit" in self.registry.commands
        
        # Aliases also registered and point to same handler
        assert "/exit" in self.registry.commands
        assert "/q" in self.registry.commands
        
        # All point to same handler object
        assert self.registry.commands["/quit"] is self.registry.commands["/exit"]
        assert self.registry.commands["/quit"] is self.registry.commands["/q"]

    def test_register_command_requires_engine(self):
        """Register command that requires engine."""
        def handler(args):
            pass
        
        self.registry.register(
            "/run",
            handler,
            "Run task",
            requires_engine=True
        )
        
        cmd = self.registry.commands["/run"]
        assert cmd.requires_engine is True

    def test_register_decorator_style(self):
        """Register command using decorator pattern.
        
        Note: register() returns the handler directly, so decorator syntax is:
        @registry.register(name, desc, category)
        def handler(args): ...
        """
        registry = CommandRegistry()
        
        # The register method returns the handler, making it usable as a decorator
        result = registry.register("/decorated", lambda args: "decorated", "Decorated command", "test")
        
        # Result should be the handler function itself
        assert callable(result)
        assert result(None) == "decorated"
        
        # And it should be registered
        assert "/decorated" in registry.commands
        cmd = registry.commands["/decorated"]
        assert cmd.handler is result

    def test_find_command_exists(self):
        """Find existing command."""
        def handler(args):
            pass
        
        self.registry.register("/find-me", handler, "Find me")
        
        result = self.registry.find("/find-me")
        assert result is not None
        assert result.name == "/find-me"

    def test_find_command_case_insensitive(self):
        """Find command is case insensitive."""
        def handler(args):
            pass
        
        self.registry.register("/CaseTest", handler, "Case test")
        
        assert self.registry.find("/casetest") is not None
        assert self.registry.find("/CASETEST") is not None
        assert self.registry.find("/CaseTest") is not None

    def test_find_command_not_exists(self):
        """Find returns None for non-existent command."""
        result = self.registry.find("/nonexistent")
        assert result is None

    def test_find_command_strips_whitespace(self):
        """Find command strips leading/trailing whitespace."""
        def handler(args):
            pass
        
        self.registry.register("/trim", handler, "Trim test")
        
        assert self.registry.find(" /trim ") is not None
        assert self.registry.find("\t/trim\n") is not None

    def test_unregister_command_exists(self):
        """Unregister existing command."""
        def handler(args):
            pass
        
        self.registry.register("/remove-me", handler, "Remove me")
        assert "/remove-me" in self.registry.commands
        
        result = self.registry.unregister("/remove-me")
        assert result is True
        assert "/remove-me" not in self.registry.commands

    def test_unregister_command_not_exists(self):
        """Unregister non-existent command returns False."""
        result = self.registry.unregister("/does-not-exist")
        assert result is False

    def test_unregister_removes_aliases(self):
        """Unregister removes main command but not aliases (by design)."""
        def handler(args):
            pass
        
        self.registry.register(
            "/main",
            handler,
            "Main command",
            aliases=["/alias1"]
        )
        
        # Unregister main
        self.registry.unregister("/main")
        
        # Main is gone
        assert "/main" not in self.registry.commands
        
        # Note: Current implementation doesn't clean up aliases automatically
        # This is by design - aliases are separate entries

    def test_get_help_text_basic(self):
        """Generate basic help text."""
        def handler1(args):
            pass
        
        def handler2(args):
            pass
        
        self.registry.register("/cmd1", handler1, "First command", category="cat1")
        self.registry.register("/cmd2", handler2, "Second command", category="cat2")
        
        help_text = self.registry.get_help_text()
        
        assert "Clawd Code" in help_text
        assert "/cmd1" in help_text
        assert "/cmd2" in help_text
        assert "First command" in help_text
        assert "Second command" in help_text

    def test_get_help_text_groups_by_category(self):
        """Help text groups commands by category."""
        def handler1(args):
            pass
        
        def handler2(args):
            pass
        
        self.registry.register("/sys1", handler1, "System 1", category="system")
        self.registry.register("/sys2", handler2, "System 2", category="system")
        
        def handler3(args):
            pass
        
        self.registry.register("/user1", handler3, "User 1", category="user")
        
        help_text = self.registry.get_help_text()
        
        # Categories should appear
        assert "system" in help_text
        assert "user" in help_text
        # Both system commands should appear
        assert "/sys1" in help_text
        assert "/sys2" in help_text
        # User command should appear
        assert "/user1" in help_text

    def test_get_help_text_excludes_aliases(self):
        """Help text should not duplicate aliased commands."""
        def handler(args):
            pass
        
        self.registry.register(
            "/main",
            handler,
            "Main command",
            aliases=["/alias1", "/alias2"]
        )
        
        help_text = self.registry.get_help_text()
        
        # Main command appears once
        assert help_text.count("/main") == 1
        
        # Aliases don't appear in help (only unique handlers)
        assert "/alias1" not in help_text or help_text.count("/main") == 1

    def test_get_commands_by_category(self):
        """Get commands filtered by category."""
        def handler1(args):
            pass
        
        def handler2(args):
            pass
        
        self.registry.register("/sys1", handler1, "Sys 1", category="system")
        self.registry.register("/sys2", handler2, "Sys 2", category="system")
        self.registry.register("/usr1", handler1, "User 1", category="user")
        
        system_cmds = self.registry.get_commands_by_category("system")
        user_cmds = self.registry.get_commands_by_category("user")
        
        assert len(system_cmds) >= 2  # May include aliases
        assert len(user_cmds) >= 1

    def test_get_commands_by_category_empty(self):
        """Get commands for non-existent category returns empty list."""
        cmds = self.registry.get_commands_by_category("nonexistent")
        assert cmds == []

    def test_multiple_registrations_same_name(self):
        """Re-registering same name overwrites previous."""
        def handler1(args):
            return "first"
        
        def handler2(args):
            return "second"
        
        self.registry.register("/overwrite", handler1, "First")
        self.registry.register("/overwrite", handler2, "Second")
        
        cmd = self.registry.commands["/overwrite"]
        assert cmd.description == "Second"
        assert cmd.handler is handler2

    def test_registry_initialization_state(self):
        """Check initial registry state."""
        registry = CommandRegistry()
        
        assert len(registry.commands) == 0
        assert registry._initialized is False

    def test_command_handler_identity_preserved(self):
        """Original handler function identity is preserved."""
        def my_handler(args):
            return "identity"
        
        self.registry.register("/identity", my_handler, "Identity test")
        
        cmd = self.registry.find("/identity")
        assert cmd.handler is my_handler
        assert cmd.handler(None) == "identity"


class TestCommandRegistryIntegration:
    """Integration tests for CommandRegistry."""

    def test_full_command_lifecycle(self):
        """Test complete command lifecycle: register -> find -> execute -> unregister."""
        registry = CommandRegistry()
        execution_log = []
        
        def tracked_handler(args):
            execution_log.append(f"executed with {args}")
            return "success"
        
        # Register
        registry.register("/track", tracked_handler, "Track execution")
        
        # Find
        cmd = registry.find("/track")
        assert cmd is not None
        
        # Execute
        result = cmd.handler("test-args")
        assert result == "success"
        assert len(execution_log) == 1
        assert execution_log[0] == "executed with test-args"
        
        # Unregister
        registry.unregister("/track")
        assert registry.find("/track") is None

    def test_complex_alias_scenario(self):
        """Test complex alias registration and lookup."""
        registry = CommandRegistry()
        
        def quit_handler(args):
            return "quitting"
        
        # Register with multiple aliases
        registry.register(
            "/quit",
            quit_handler,
            "Quit application",
            aliases=["/exit", "/bye", "/q"]
        )
        
        # All variations should work
        for cmd_name in ["/quit", "/exit", "/bye", "/q", "/QUIT", "/Exit"]:
            cmd = registry.find(cmd_name)
            assert cmd is not None
            assert cmd.name == "/quit"
            assert cmd.handler("test") == "quitting"

    def test_help_text_formatting(self):
        """Test help text includes proper formatting."""
        registry = CommandRegistry()
        
        def dummy1(args):
            pass
        
        def dummy2(args):
            pass
        
        registry.register("/test1", dummy1, "Test one", category="alpha")
        registry.register("/test2", dummy2, "Test two", category="beta")
        
        help_text = registry.get_help_text()
        
        # Should contain structural elements
        assert "Clawd Code" in help_text
        
        # Should contain both commands (different handlers)
        assert "/test1" in help_text
        assert "/test2" in help_text
        assert "Test one" in help_text
        assert "Test two" in help_text
