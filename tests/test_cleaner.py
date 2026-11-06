from agent_janitor.cleaner import Cleaner


def plenty_of_space(_path):
    return 100, 90


def test_removes_only_old_workspaces(cfg, make_ws):
    old = make_ws("job-old", age_days=5)
    fresh = make_ws("job-fresh", age_days=1)

    report = Cleaner(cfg, disk_usage=plenty_of_space).run()

    assert not old.exists()
    assert fresh.exists()
    assert report.removed == [old]
    assert report.bytes_reclaimed == 1024


def test_lock_file_protects_running_build(cfg, make_ws):
    ws = make_ws("job-running", age_days=10)
    (ws / ".janitor-keep").touch()

    report = Cleaner(cfg, disk_usage=plenty_of_space).run()

    assert ws.exists()
    assert report.skipped_protected == 1


def test_keep_patterns(cfg, make_ws):
    ws = make_ws("job@tmp", age_days=10)
    Cleaner(cfg, disk_usage=plenty_of_space).run()
    assert ws.exists()


def test_dry_run_deletes_nothing(cfg, make_ws):
    cfg.dry_run = True
    ws = make_ws("job-old", age_days=10)

    report = Cleaner(cfg, disk_usage=plenty_of_space).run()

    assert ws.exists()
    assert report.removed == [ws]


def test_space_pass_removes_lru_until_threshold(cfg, make_ws):
    """Disk is 5% free; each removal frees 10%. Want 20% -> remove the 2 oldest."""
    cfg.min_free_percent = 20
    a = make_ws("a", age_days=2.5)
    b = make_ws("b", age_days=2.0)
    c = make_ws("c", age_days=0.5)

    def disk(_path):
        removed = sum(not p.exists() for p in (a, b, c))
        return 100, 5 + 10 * removed

    report = Cleaner(cfg, disk_usage=disk).run()

    assert not a.exists() and not b.exists()
    assert c.exists()
    assert report.free_percent_after == 25


def test_space_pass_dry_run_estimates_from_sizes(cfg, make_ws):
    cfg.min_free_percent = 50
    cfg.dry_run = True
    make_ws("a", age_days=2, size=30)
    make_ws("b", age_days=1, size=30)
    make_ws("c", age_days=0, size=30)

    report = Cleaner(cfg, disk_usage=lambda _p: (100, 0)).run()

    # 0 free -> after a: 30 -> after b: 60 >= 50, stop
    assert [p.name for p in report.removed] == ["a", "b"]


def test_missing_root_is_not_fatal(cfg, tmp_path):
    cfg.roots = [tmp_path / "nope"]
    report = Cleaner(cfg, disk_usage=plenty_of_space).run()
    assert report.removed == []
