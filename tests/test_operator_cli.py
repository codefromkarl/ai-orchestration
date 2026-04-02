from taskplane.operator_cli import main


def test_operator_cli_dispatches_list_subcommand_and_forwards_args():
    captured: dict[str, object] = {}

    def fake_list_main(argv):
        captured["argv"] = list(argv)
        return 11

    exit_code = main(
        ["list", "--repo", "codefromkarl/stardrifter", "--include-closed"],
        list_main=fake_list_main,
    )

    assert exit_code == 11
    assert captured["argv"] == [
        "--repo",
        "codefromkarl/stardrifter",
        "--include-closed",
    ]


def test_operator_cli_dispatches_ack_subcommand_and_forwards_args():
    captured: dict[str, object] = {}

    def fake_ack_main(argv):
        captured["argv"] = list(argv)
        return 7

    exit_code = main(
        [
            "ack",
            "--repo",
            "codefromkarl/stardrifter",
            "--epic-issue-number",
            "13",
            "--reason-code",
            "progress_timeout",
            "--closed-reason",
            "acknowledged",
        ],
        ack_main=fake_ack_main,
    )

    assert exit_code == 7
    assert captured["argv"] == [
        "--repo",
        "codefromkarl/stardrifter",
        "--epic-issue-number",
        "13",
        "--reason-code",
        "progress_timeout",
        "--closed-reason",
        "acknowledged",
    ]


def test_operator_cli_dispatches_report_subcommand_and_forwards_args():
    captured: dict[str, object] = {}

    def fake_report_main(argv):
        captured["argv"] = list(argv)
        return 3

    exit_code = main(
        ["report", "--repo", "codefromkarl/stardrifter"],
        report_main=fake_report_main,
    )

    assert exit_code == 3
    assert captured["argv"] == ["--repo", "codefromkarl/stardrifter"]
