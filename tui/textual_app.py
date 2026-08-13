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
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "orchestrator"))
import config
from pipeline_runner import run_pipeline
from state import PipelineState


class StartScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Hello, let's build something...", id="banner")
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
        yield Input(placeholder="Write the spec here...")
        yield Footer()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        spec = event.value.strip()
        if spec:
            self.app.spec = spec
            self.app.pop_screen()
            self.app.push_screen(EngineScreen())


class EngineScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Which engine should build this?")
        yield OptionList(
            Option("MCP pipeline (re_engineer -> dev)", id="mcp"),
            #Option("Claude Code (via sandbox MCP)", id="claude_code"),
            #Option("opencode (via sandbox MCP)", id="opencode"),
        )
        yield Footer()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        engine = event.option.id
        config.ENGINE = engine
        self.app.engine = engine
        self.app.pop_screen()
        if engine == "mcp":
            self.app.push_screen(ModelScreen())
        else:
            self.app.model_label = engine
            self.app.start_pipeline()


class ModelScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Which model should power the MCP pipeline?")
        yield OptionList(
            Option("Groq: qwen/qwen3.6-27b", id="groq:qwen/qwen3.6-27b"),
            Option("Groq: gpt-oss-120b", id="groq:openai/gpt-oss-120b"),
        )
        yield Footer()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        profile, model = event.option.id.split(":", 1)
        config.MODEL_PROFILE = profile
        if profile == "groq":
            config.USED_MODEL = model
        else:
            config.LLAMACPP_MODEL = config.LLAMACPP_MODEL or model
        self.app.model_label = model
        self.app.pop_screen()
        self.app.start_pipeline()


class CheckpointScreen(Screen[str]):
    """Shown after each stage. Returns 'approve' or 'reject' via dismiss()."""

    def __init__(self, role: str, artifact: str, workspace: Path):
        super().__init__()
        self.role = role
        self.artifact = artifact
        self.workspace = workspace

    def _list_files(self) -> list[Path]:
        return sorted(
            p for p in self.workspace.rglob("*")
            if p.is_file() and not any(part in config.KNOWN_ARTIFACT_DIRS for part in p.parts)
        )

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(f"--- Checkpoint: {self.role} ---")
        yield Static(self.artifact[:1000], id="artifact-preview")
        options = [Option("Approve", id="approve"), Option("Reject", id="reject")]
        for f in self._list_files():
            rel = str(f.relative_to(self.workspace))
            options.append(Option(f"View: {rel}", id=f"view:{rel}"))
        yield OptionList(*options)
        yield Footer()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = event.option.id or ""
        if option_id.startswith("view:"):
            rel_path = option_id[len("view:"):]
            try:
                content = (self.workspace / rel_path).read_text()
            except Exception as e:
                content = f"Could not read {rel_path}: {e}"
            self.query_one("#artifact-preview", Static).update(f"--- {rel_path} ---\n{content}")
            return
        self.dismiss(option_id)


class RunningScreen(Screen):
    """Live tool-call stream while a stage is executing, plus a
    continuously-updating status line so it's always clear whether the
    pipeline is working or has actually stalled/crashed."""

    SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self):
        super().__init__()
        self._status_text = "Starting..."
        self._spinner_index = 0
        self._stage_started_at = time.monotonic()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Working...", id="role-status")
        yield Static("", id="status-line")
        yield RichLog(id="stream", wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(0.1, self._tick)

    def _tick(self) -> None:
        elapsed = time.monotonic() - self._stage_started_at
        frame = self.SPINNER_FRAMES[self._spinner_index % len(self.SPINNER_FRAMES)]
        self._spinner_index += 1
        self.query_one("#status-line", Static).update(f"{frame} {self._status_text}  ({elapsed:.0f}s)")

    def log_line(self, message: str) -> None:
        self.query_one("#stream", RichLog).write(message)

    def set_status(self, text: str) -> None:
        self._status_text = text

    def set_role(self, role: str) -> None:
        self._stage_started_at = time.monotonic()
        self._status_text = "Starting..."
        self.query_one("#role-status", Static).update(f"Agent: {role}")


class PipelineApp(App):
    BINDINGS = [Binding("ctrl+c", "hard_stop", "Hard stop", priority=True)]
    CSS = """
    #banner { padding: 1 2; }
    """

    def __init__(self):
        super().__init__()
        self.spec: str | None = None
        self.engine: str = config.ENGINE
        self.model_label: str = ""
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
        os.makedirs(config.RUN_LOGS_DIR, exist_ok=True)
        try:
            running = RunningScreen()
            await self.push_screen(running)

            workspace = config.DEMO_PROJECT_DIR / "test_run"
            os.makedirs(workspace, exist_ok=True)
            log_path = config.RUN_LOGS_DIR / "test_run.json"
            state = PipelineState(
                spec=self.spec, project_slug="test_run", workspace=str(workspace),
                engine=self.engine, model=self.model_label,
            )

            async def checkpoint_fn(role: str, artifact: str, ws: Path) -> str:
                return await self.push_screen_wait(CheckpointScreen(role, artifact, ws))

            await run_pipeline(
                config.ENGINE, self.spec, workspace, log_path, state,
                checkpoint_fn=checkpoint_fn, log_fn=running.log_line,
                role_fn=running.set_role, status_fn=running.set_status,
            )
        except Exception:
            crash_log = config.CRASH_LOGS_DIR / f"crash_{int(time.time())}.log"
            crash_log.write_text(traceback.format_exc())
            self.exit(message=f"Pipeline crashed - stack trace saved to {crash_log}")


if __name__ == "__main__":
    PipelineApp().run()