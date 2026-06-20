import json
import pathlib

import recommend

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
SCORES = str(FIXTURES / "recommend_scores_sample.json")
CONFIG = str(pathlib.Path(__file__).parents[1] / "skills/recommend/config/recommend.json")


def test_default_paths_anchor_on_the_skills_tree():
    assert pathlib.Path(recommend.DEFAULT_SCORES).name == "vault_scores.json"
    assert pathlib.Path(recommend.DEFAULT_CONFIG).name == "recommend.json"


def test_main_prints_bucketized_json(capsys):
    assert recommend.main(["--asset", "USDT", "--scores", SCORES, "--config", CONFIG]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["asset"] == "USDT"
    assert [r["pool"] for r in out["buckets"]["conservative"]] == ["c2", "c1"]
    assert [r["pool"] for r in out["reps"]["conservative"]] == ["c2", "c1"]
    assert out["counts"]["excluded"] == 4
    assert out["generated_at"] == "2026-06-17T18:00:00Z"


def test_main_fails_without_score_cache(tmp_path, capsys):
    assert recommend.main(["--asset", "USDT", "--scores", str(tmp_path / "absent.json"),
                           "--config", CONFIG]) == 1
    assert "Score cache not found" in capsys.readouterr().err


def test_main_fails_without_config(tmp_path, capsys):
    assert recommend.main(["--asset", "USDT", "--scores", SCORES,
                           "--config", str(tmp_path / "absent.json")]) == 1
    assert "Config not found" in capsys.readouterr().err
