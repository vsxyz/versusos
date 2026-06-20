import json
import pathlib

SKILL = pathlib.Path(__file__).resolve().parents[1] / "skills" / "inspect"


def test_config_has_required_keys():
    config = json.loads((SKILL / "config" / "inspect.json").read_text())
    assert set(config) >= {"covered_chains", "naming_enabled", "top_picks", "table"}
    assert isinstance(config["covered_chains"], list) and config["covered_chains"]
    assert config["naming_enabled"] is True
    assert config["top_picks"] == 3 and config["table"] == 10


def test_skill_md_exists_with_frontmatter():
    text = (SKILL / "SKILL.md").read_text()
    assert text.startswith("---")
    assert "name: inspect" in text
