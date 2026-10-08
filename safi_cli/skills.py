"""Discovery and execution for repository-local custom skills (.safi/skills/)."""
from pathlib import Path
from typing import Dict, Any, List, Optional
import os


class LocalSkill:
    def __init__(self, name: str, description: str, prompt_template: str, file_path: Path):
        self.name = name.strip().lower()
        self.description = description.strip()
        self.prompt_template = prompt_template.strip()
        self.file_path = file_path

    def render_prompt(self, user_args: str = "") -> str:
        if "{args}" in self.prompt_template:
            return self.prompt_template.replace("{args}", user_args.strip())
        if user_args.strip():
            return f"{self.prompt_template}\n\nContext / Arguments:\n{user_args.strip()}"
        return self.prompt_template


def discover_skills(workspace_root: Path) -> Dict[str, LocalSkill]:
    """Scan workspace_root/.safi/skills/ for skill files (.md or .txt)."""
    skills: Dict[str, LocalSkill] = {}
    skills_dir = workspace_root / ".safi" / "skills"
    if not skills_dir.exists() or not skills_dir.is_dir():
        return skills

    for item in sorted(skills_dir.iterdir()):
        if item.is_file() and item.suffix.lower() in (".md", ".txt"):
            try:
                content = item.read_text(encoding="utf-8", errors="replace")
                skill_name = item.stem.lower()

                # Parse frontmatter / header if present
                lines = content.splitlines()
                description = f"Local skill: {skill_name}"
                body_lines = []

                if lines and lines[0].strip().startswith("#"):
                    description = lines[0].strip().lstrip("#").strip()
                    body_lines = lines[1:]
                else:
                    body_lines = lines

                prompt_template = "\n".join(body_lines).strip()
                if not prompt_template:
                    prompt_template = content.strip()

                skills[skill_name] = LocalSkill(
                    name=skill_name,
                    description=description,
                    prompt_template=prompt_template,
                    file_path=item,
                )
            except Exception:
                continue

    return skills
