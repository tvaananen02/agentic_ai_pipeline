from dataclasses import dataclass, field
import json
from pathlib import Path
 
 
@dataclass
class PipelineState:
    spec: str
    project_slug: str
    workspace: str
    stage_results: dict = field(default_factory=dict)
 
    def record(self, role: str, result: str, approved: bool):
        self.stage_results[role] = {"result": result, "approved": approved}
 
    def save(self, path: Path):
        path.write_text(json.dumps({
            "spec": self.spec,
            "project_slug": self.project_slug,
            "workspace": self.workspace,
            "stage_results": self.stage_results,
        }, indent=2))
 
