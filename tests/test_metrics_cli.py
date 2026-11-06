import json

from agent_janitor import cli, metrics
from agent_janitor.cleaner import Report


def test_render_has_help_type_and_labels():
    text = metrics.render(Report(bytes_reclaimed=2048), agent="build-01", dry_run=False, now=1)
    assert "# TYPE agent_janitor_bytes_reclaimed gauge" in text
    assert 'agent_janitor_bytes_reclaimed{agent="build-01",dry_run="false"} 2048' in text


def test_write_atomic(tmp_path):
    target = tmp_path / "textfile" / "janitor.prom"
    metrics.write_atomic(target, "x 1\n")
    assert target.read_text() == "x 1\n"
    assert [p.name for p in target.parent.iterdir()] == ["janitor.prom"]


def test_cli_json_and_metrics(tmp_path, make_ws, capsys):
    root = tmp_path / "ws"
    make_ws("old", age_days=9, root=root)
    prom = tmp_path / "janitor.prom"

    rc = cli.main(
        [
            str(root),
            "--max-age-days",
            "3",
            "--min-free-percent",
            "0",
            "--metrics-file",
            str(prom),
            "--json",
        ]
    )

    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["removed"] == 1
    assert "agent_janitor_workspaces_removed" in prom.read_text()


def test_cli_rejects_missing_roots(capsys):
    assert cli.main([]) == 2


def test_config_file(tmp_path):
    conf = tmp_path / "janitor.toml"
    conf.write_text('[janitor]\nroots = ["/srv/ci"]\nmax_age_days = 7\n')
    cfg = cli.build_config(cli.parse_args(["-c", str(conf)]))
    assert cfg.max_age_days == 7
    assert str(cfg.roots[0]) == "/srv/ci"
