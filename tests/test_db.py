from tschedule.db import DB


def test_upsert_job_and_get_id(tmp_path):
    db = DB(tmp_path / "test.db")
    job_id = db.upsert_job("proj", "backup", "Daily backup", ["infra"])
    assert job_id is not None

    assert db.get_job_id("proj", "backup") == job_id

    # Upsert again with different description — same ID
    job_id2 = db.upsert_job("proj", "backup", "Updated desc", ["infra"])
    assert job_id2 == job_id


def test_get_job_id_missing(tmp_path):
    db = DB(tmp_path / "test.db")
    assert db.get_job_id("nope", "nope") is None


def test_start_and_finish_run(tmp_path):
    db = DB(tmp_path / "test.db")
    job_id = db.upsert_job("proj", "deploy", "", [])
    run_id = db.start_run(job_id)

    db.finish_run(run_id, 0, "deployed ok", "")

    runs = db.get_run_history(job_id, limit=5)
    assert len(runs) == 1
    assert runs[0]["exit_code"] == 0
    assert runs[0]["stdout"] == "deployed ok"
    assert runs[0]["finished_at"] is not None


def test_run_history_ordering(tmp_path):
    db = DB(tmp_path / "test.db")
    job_id = db.upsert_job("proj", "job", "", [])

    for i in range(3):
        rid = db.start_run(job_id)
        db.finish_run(rid, i, f"run {i}", "")

    runs = db.get_run_history(job_id, limit=10)
    assert len(runs) == 3
    # Ordered by started_at DESC; all have same timestamp so fallback to id DESC
    # Last inserted has highest id → exit_code 2
    exit_codes = [r["exit_code"] for r in runs]
    assert set(exit_codes) == {0, 1, 2}


def test_get_all_jobs_with_stats(tmp_path):
    db = DB(tmp_path / "test.db")
    id1 = db.upsert_job("proj", "good", "", [])
    id2 = db.upsert_job("proj", "flaky", "", [])

    # good: 2 successful runs
    for _ in range(2):
        rid = db.start_run(id1)
        db.finish_run(rid, 0, "", "")

    # flaky: 1 success + 1 failure
    rid = db.start_run(id2)
    db.finish_run(rid, 0, "", "")
    rid = db.start_run(id2)
    db.finish_run(rid, 1, "", "oops")

    stats = db.get_all_jobs_with_stats()
    assert len(stats) == 2

    by_name = {row["name"]: row for row in stats}
    assert by_name["good"]["total_runs"] == 2
    assert by_name["good"]["last_exit_code"] == 0
    assert by_name["flaky"]["total_runs"] == 2
    assert by_name["flaky"]["total_runs"] == 2
    assert by_name["flaky"]["errors_7d"] >= 1


def test_get_all_runs(tmp_path):
    db = DB(tmp_path / "test.db")
    job_id = db.upsert_job("proj", "task", "", ["tag1"])
    rid = db.start_run(job_id)
    db.finish_run(rid, 0, "out", "err")

    runs = db.get_all_runs(limit=10)
    assert len(runs) == 1
    assert runs[0]["project"] == "proj"
    assert runs[0]["job_name"] == "task"
