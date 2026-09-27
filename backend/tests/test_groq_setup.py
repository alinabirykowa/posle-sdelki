import os
from pathlib import Path

import pytest

from scripts.setup_groq import save_configuration


def test_setup_preserves_database_and_stores_private_file(tmp_path, capsys):
    path = tmp_path / ".env"
    path.write_text("# keep\nDATABASE_URL=existing-database\nLLM_PROVIDER=vercel\nexport LLM_MODEL=old/model\n")
    key = "gsk_test_only_not_a_real_credential"
    save_configuration(path, key, "qwen/qwen3.8-27b")
    text = path.read_text()
    assert "DATABASE_URL=existing-database" in text
    assert "# keep" in text
    assert text.count("LLM_PROVIDER=") == 1
    assert "LLM_PROVIDER=groq\n" in text
    assert "GROQ_API_KEY=" + key in text
    assert "LLM_REPLY_MODE=generated" in text
    assert "old/model" not in text
    assert os.stat(path).st_mode & 0o777 == 0o600
    captured = capsys.readouterr()
    assert key not in captured.out + captured.err


@pytest.mark.parametrize("key", ["", "wrong-key", "gsk_short", "gsk_" + "x" * 20 + "\nINJECTED=1"])
def test_bad_key_leaves_original_file_intact(tmp_path, key):
    path = tmp_path / ".env"
    path.write_text("DATABASE_URL=unchanged\n")
    with pytest.raises(ValueError):
        save_configuration(path, key, "qwen/qwen3.8-27b")
    assert path.read_text() == "DATABASE_URL=unchanged\n"
