"""
Textual-based TUI for the pipeline. Replaces the simple_term_menu screens.

Key design point, confirmed by direct testing before writing this: Textual
runs the terminal in raw mode, so Ctrl+C does NOT raise KeyboardInterrupt
the way it did with simple_term_menu/plain input(). Instead, Ctrl+C is
bound explicitly (see BINDINGS) to cancel the currently running pipeline
worker - asyncio.CancelledError from worker cancellation was confirmed to
correctly propagate through `async with stdio_client(...)` and run its
cleanup, same end result as the old KeyboardInterrupt path, just a
different trigger mechanism.
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
from pipeline_runner import run_stage, launch_persistent_app, run_alt_engine, prepare_project_dir
from state import PipelineState
import asyncio


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

        if config.ENGINE != "mcp":
            running.set_role(config.ENGINE)
            running.log_line(f"Running via {config.ENGINE} (this can take a while)...")
            # run_alt_engine is a blocking sync call (subprocess.run inside it) -
            # run it in a thread so it doesn't freeze the whole UI event loop.
            approved, output = await asyncio.to_thread(run_alt_engine, config.ENGINE, workspace, self.spec)
            running.log_line(output[:1000])
            state.record(config.ENGINE, output, approved)
            state.save(log_path)
            if not approved:
                running.log_line(f"{config.ENGINE}: AUTO-REJECTED, stopping.")
                return
            decision = await checkpoint_fn(config.ENGINE, output)
            if decision != "approve":
                running.log_line(f"{config.ENGINE}: Not approved, stopping.")
                return
            running.log_line(f"Done. Files in {workspace}")
            return

        last_tool_calls: list[dict] = []
        for role in config.PIPELINE_ORDER:
            running.set_role(role)
            approved, tool_calls = await run_stage(
                role, workspace, self.spec, state, log_path,
                log_fn=running.log_line, checkpoint_fn=checkpoint_fn,
            )
            if role == "se_engineer":
                last_tool_calls = tool_calls
            if not approved:
                running.log_line(f"{role}: Not approved, stopping.")
                return
            if role == "tester":
                project_name = prepare_project_dir(workspace)
                if project_name:
                    running.log_line(f"Project directory '{project_name}' created, test file copied in (deterministically).")
                else:
                    running.log_line("WARNING: could not determine project name / find test files.")

        url = launch_persistent_app(last_tool_calls, workspace)
        running.log_line(f"Done. App running: {url}" if url else "Done. No persistent server started.")


if __name__ == "__main__":
    PipelineApp().run()