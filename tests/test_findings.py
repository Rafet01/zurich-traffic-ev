import json

import pytest
from findings import END, START, is_synthetic, replace_block


def test_replace_block_keeps_everything_around_it():
    readme = f"# Title\n\n## Findings\n\n{START}\n_pending_\n{END}\n\n## Next\n"
    out = replace_block(readme, "**1.** busy at 07:00\n")
    assert out == f"# Title\n\n## Findings\n\n{START}\n**1.** busy at 07:00\n{END}\n\n## Next\n"
    assert replace_block(out, "x\n").count(START) == 1


def test_replace_block_needs_the_markers():
    with pytest.raises(ValueError):
        replace_block("# no markers\n", "x\n")


def test_synthetic_data_is_recognised_on_any_os(tmp_path):
    m = tmp_path / "manifest.jsonl"
    real = {"status": "loaded", "source_uri": "https://data.stadt-zuerich.ch/x_2026.csv"}
    fixture = {"status": "loaded", "source_uri": r"C:\repo\tests\fixtures\traffic\x_2026.csv"}
    m.write_text(json.dumps(real) + "\n", encoding="utf-8")
    assert not is_synthetic(m)
    m.write_text(json.dumps(real) + "\n" + json.dumps(fixture) + "\n", encoding="utf-8")
    assert is_synthetic(m)
