"""
Textual-based TUI for the pipeline.
"""
from __future__ import annotations
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Header, Footer, Static, Input, OptionList, RichLog
from textual.widgets.option_list import Option
from textual.screen import Screen
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "orchestrator"))
import config
from pipeline_runner import run_pipeline
from state import PipelineState


class StartScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Hello human, let's build something...", id="banner")
        yield OptionList(
            Option("Start building", id="start"),
            Option("Quit", id="quit"),
        )
        yield Footer()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id == "quit":
            self.app.exit()
        else:
            self.app.push_screen(SpecScreen())


class SpecScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("What should we build?")
        yield Input(placeholder="a command line tool that checks if a number is prime")
        yield Footer()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        spec = event.value.strip()
        if spec:
            self.app.spec = spec
            self.app.pop_screen()
            self.app.start_pipeline()


class CheckpointScreen(Screen[str]):
    """Shown after each stage. Returns 'approve' or 'reject' via dismiss()."""

    def __init__(self, role: str, artifact: str):
        super().__init__()
        self.role = role
        self.artifact = artifact

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(f"--- Checkpoint: {self.role} ---")
        yield Static(self.artifact[:1000], id="artifact-preview")
        yield OptionList(
            Option("Approve", id="approve"),
            Option("Reject", id="reject"),
            Option("View full", id="view"),
        )
        yield Footer()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id == "view":
            self.query_one("#artifact-preview", Static).update(self.artifact)
            return
        self.dismiss(event.option.id)


class RunningScreen(Screen):
    """Live tool-call stream while a stage is executing."""

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Working...", id="role-status")
        yield RichLog(id="stream", wrap=True)
        yield Footer()

    def log_line(self, message: str) -> None:
        self.query_one("#stream", RichLog).write(message)

    def set_role(self, role: str) -> None:
        self.query_one("#role-status", Static).update(f"Agent: {role}")


class PipelineApp(App):
    BINDINGS = [Binding("ctrl+c", "hard_stop", "Hard stop", priority=True)]
    CSS = """
    #banner { padding: 1 2; }
    """

    def __init__(self):
        super().__init__()
        self.spec: str | None = None
        self.pipeline_worker = None

    def on_mount(self) -> None:
        self.push_screen(StartScreen())

    def action_hard_stop(self) -> None:
        if self.pipeline_worker is not None:
            self.pipeline_worker.cancel()
        self.exit(message="Interrupted - cleaning up.")

    def start_pipeline(self) -> None:
        self.pipeline_worker = self.run_worker(self._run_pipeline())

    async def _run_pipeline(self) -> None:
        running = RunningScreen()
        await self.push_screen(running)

        workspace = config.DEMO_PROJECT_DIR / "test_run"
        os.makedirs(workspace, exist_ok=True)
        os.makedirs(config.RUN_LOGS_DIR, exist_ok=True)
        log_path = config.RUN_LOGS_DIR / "test_run.json"
        state = PipelineState(spec=self.spec, project_slug="test_run", workspace=str(workspace))

        async def checkpoint_fn(role: str, artifact: str) -> str:
            return await self.push_screen_wait(CheckpointScreen(role, artifact))

        await run_pipeline(
            config.ENGINE, self.spec, workspace, log_path, state,
            checkpoint_fn=checkpoint_fn, log_fn=running.log_line, role_fn=running.set_role,
        )


if __name__ == "__main__":
    PipelineApp().run()