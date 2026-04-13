"""Rich HUD placeholder to restore system integrity."""
from rich.console import Console

from .hud import HudContext


class RichLiveHud:
    def __init__(self):
        self.console = Console()
        self.renderer = type('DummyRenderer', (), {
            'state': HudContext(),
            'render_full_layout': lambda: ""
        })()

    def set_max_iterations(self, n): pass
    def stream_content(self, content): pass
    def update_iteration(self, n): pass
    def update_status(self, status, msg): pass
    def add_step(self, type, action, success): pass
    def update_tokens(self, tokens, cost): pass
