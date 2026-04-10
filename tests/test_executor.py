import subprocess
from unittest.mock import patch, MagicMock

from tschedule.config import JobConfig
from tschedule.db import DB
from tschedule.executor import run_job


def _job(**kwargs):
    defaults = dict(
        name="test-job",
        project="test-proj",
        command="echo hello",
        timeout=30,
        retries=0,
    )
    defaults.update(kwargs)
    return JobConfig(**defaults)


def _mock_result(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


@patch("tschedule.executor.subprocess.run")
def test_run_job_success(mock_run, tmp_path):
    mock_run.return_value = _mock_result(0, "hello\n", "")
    db = DB(tmp_path / "test.db")

    code, out, err = run_job(_job(), db)

    assert code == 0
    assert out == "hello\n"
    mock_run.assert_called_once()

    runs = db.get_all_runs(limit=1)
    assert runs[0]["exit_code"] == 0


@patch("tschedule.executor.subprocess.run")
def test_run_job_failure(mock_run, tmp_path):
    mock_run.return_value = _mock_result(1, "", "fail")
    db = DB(tmp_path / "test.db")

    code, out, err = run_job(_job(), db)

    assert code == 1
    assert err == "fail"

    runs = db.get_all_runs(limit=1)
    assert runs[0]["exit_code"] == 1


@patch("tschedule.executor.subprocess.run")
def test_run_job_timeout(mock_run, tmp_path):
    exc = subprocess.TimeoutExpired(cmd="echo", timeout=30)
    exc.stdout = b"partial"
    mock_run.side_effect = exc
    db = DB(tmp_path / "test.db")

    code, out, err = run_job(_job(timeout=30), db)

    assert code == 124
    assert "Timeout" in err
    assert out == "partial"


@patch("tschedule.executor.subprocess.run")
def test_run_job_retries_then_succeeds(mock_run, tmp_path):
    mock_run.side_effect = [
        _mock_result(1, "", "err1"),
        _mock_result(1, "", "err2"),
        _mock_result(0, "ok", ""),
    ]
    db = DB(tmp_path / "test.db")

    code, out, err = run_job(_job(retries=2), db)

    assert code == 0
    assert out == "ok"
    assert mock_run.call_count == 3


@patch("tschedule.executor.subprocess.run")
def test_run_job_retries_all_fail(mock_run, tmp_path):
    mock_run.return_value = _mock_result(1, "", "nope")
    db = DB(tmp_path / "test.db")

    code, out, err = run_job(_job(retries=1), db)

    assert code == 1
    assert mock_run.call_count == 2
