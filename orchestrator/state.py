from dataclasses import dataclass, field
import json
from pathlib import Path
from datetime import datetime, timezone

@dataclass
class PipelineState:
    spec: str
    project_slug: str
    workspace: str
    engine: str = ""
    model: str = ""
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: str | None = None
    deploy_url: str | None = None
    stage_results: dict = field(default_factory=dict)

    def record(
        self,
        role: str,
        result: str,
        approved: bool,
        rejection_reason: str | None = None,
        tool_calls: list[dict] | None = None,
    ):
        self.stage_results[role] = {
            "result": result,
            "approved": approved,
            "rejection_reason": rejection_reason,
            "tool_call_names": [tc.get("name") for tc in (tool_calls or [])],
            "tool_call_count": len(tool_calls or []),
        }

    def record_deploy(self, url: str | None):
        self.deploy_url = url

    def finish(self):
        self.finished_at = datetime.now(timezone.utc).isoformat()

    def save(self, path: Path):
        path.write_text(json.dumps({
            "spec": self.spec,
            "project_slug": self.project_slug,
            "workspace": self.workspace,
            "engine": self.engine,
            "model": self.model,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "deploy_url": self.deploy_url,
            "stage_results": self.stage_results,
        }, indent=2))