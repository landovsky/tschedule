from tschedule.config import JobConfig
from tschedule.units import unit_name, write_units, list_managed_units, sync_units


def _job(name="backup", project="myproj", **kwargs):
    defaults = dict(
        schedule="0 2 * * *",
        command="/usr/bin/backup.sh",
        working_dir="/data",
        timeout=300,
    )
    defaults.update(kwargs)
    return JobConfig(name=name, project=project, **defaults)


def test_unit_name():
    assert unit_name("myproj", "backup") == "tschedule-myproj-backup"


def test_unit_name_slashes():
    assert unit_name("my/proj", "a/b") == "tschedule-my-proj-a-b"


def test_unit_name_spaces():
    assert unit_name("my proj", "a job") == "tschedule-my_proj-a_job"


def test_write_units_creates_files(tmp_path):
    job = _job()
    name = write_units(job, unit_dir=tmp_path)
    assert name == "tschedule-myproj-backup"
    assert (tmp_path / f"{name}.service").exists()
    assert (tmp_path / f"{name}.timer").exists()


def test_service_content(tmp_path):
    job = _job(env={"MY_VAR": "hello"})
    name = write_units(job, unit_dir=tmp_path)
    content = (tmp_path / f"{name}.service").read_text()
    assert "Type=oneshot" in content
    assert "ExecStart=" in content
    assert "_exec myproj backup" in content
    assert "WorkingDirectory=/data" in content
    assert 'Environment="MY_VAR=hello"' in content


def test_timer_content(tmp_path):
    job = _job()
    name = write_units(job, unit_dir=tmp_path)
    content = (tmp_path / f"{name}.timer").read_text()
    assert "OnCalendar=" in content
    assert "Persistent=true" in content
    assert "WantedBy=timers.target" in content


def test_list_managed_units(tmp_path):
    (tmp_path / "tschedule-proj-a.timer").write_text("")
    (tmp_path / "tschedule-proj-b.timer").write_text("")
    (tmp_path / "other.timer").write_text("")

    result = list_managed_units(unit_dir=tmp_path)
    assert result == {"tschedule-proj-a", "tschedule-proj-b"}


def test_sync_units_dry_run(tmp_path):
    jobs = [_job(name="a"), _job(name="b")]
    result = sync_units(jobs, unit_dir=tmp_path, dry_run=True)
    assert len(result["written"]) == 2
    assert (tmp_path / "tschedule-myproj-a.service").exists()
    assert (tmp_path / "tschedule-myproj-b.timer").exists()


def test_sync_units_removes_orphans(tmp_path):
    # Pre-create an orphan
    (tmp_path / "tschedule-old-job.timer").write_text("")
    (tmp_path / "tschedule-old-job.service").write_text("")

    jobs = [_job(name="new")]
    result = sync_units(jobs, unit_dir=tmp_path, dry_run=True)

    assert "tschedule-old-job" in result["removed"]
    assert not (tmp_path / "tschedule-old-job.timer").exists()
    assert not (tmp_path / "tschedule-old-job.service").exists()
