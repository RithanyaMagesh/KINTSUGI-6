"""Replay loading tests (BACKEND_SPEC v1.1 sections 5.2, 11): no sim dependency."""

import json

from cubesat.replay import index_at, list_logs, load_jsonl


def _write_jsonl(path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_replay_load_good_lines(tmp_path):
    header = {"v": 1, "t": 0.0, "state": "INIT", "scenario": "two_failure", "seed": 42,
              "n_sats": 6}
    tick0 = {"v": 1, "t": 0.0, "state": "NOMINAL", "coverage": 0.5, "min_sep": 100.0,
             "sats": [{"id": 0, "role": "leader", "status": "NOMINAL", "r": [0, 0, 0],
                       "v": [0, 0, 0], "dv_used": 0.0}]}
    tick1 = dict(tick0, t=2.0)
    summary = {"v": 1, "t": 2.0, "state": "SUMMARY", "coverage_mean_last_orbit": 0.49}
    path = tmp_path / "good.jsonl"
    lines = [header, tick0, tick1, summary]
    _write_jsonl(path, [json.dumps(line, sort_keys=True) for line in lines])
    log = load_jsonl(path)
    assert log.header == header
    assert log.summary == summary
    assert log.frames == [tick0, tick1]
    assert log.times == [0.0, 2.0]
    assert log.skipped == 0


def test_replay_load_bad_lines_skipped(tmp_path):
    header = {"v": 1, "t": 0.0, "state": "INIT", "scenario": "s", "seed": 1, "n_sats": 1}
    tick = {"v": 1, "t": 0.0, "state": "NOMINAL", "coverage": 0.5, "min_sep": 1.0,
            "sats": []}
    path = tmp_path / "corrupt.jsonl"
    _write_jsonl(
        path,
        [
            json.dumps(header, sort_keys=True),
            "{not valid json",  # syntax error
            json.dumps([1, 2, 3]),  # valid JSON, not an object
            json.dumps({"foo": "bar"}),  # object with neither t nor sats nor INIT/SUMMARY
            json.dumps(tick, sort_keys=True),
        ],
    )
    log = load_jsonl(path)
    assert log.frames == [tick]
    assert log.times == [0.0]
    assert log.header == header
    assert log.summary is None
    assert log.skipped == 3


def test_replay_load_schema_malformed_lines_skipped(tmp_path):
    """Section 7.1 at the message-content level: a line that parses as JSON but
    whose sats / ASSIGNMENT rows miss required fields is skipped + counted, not
    a mid-stream KeyError in the driver."""
    header = {"v": 1, "t": 0.0, "state": "INIT", "scenario": "s", "seed": 1, "n_sats": 1}
    tick = {"v": 1, "t": 0.0, "state": "NOMINAL", "coverage": 0.5, "min_sep": 1.0,
            "sats": [{"id": 0, "role": "leader", "status": "NOMINAL", "r": [0, 0, 0],
                      "v": [0, 0, 0], "dv_used": 0.0}]}
    assignment = {"v": 1, "t": 1.0, "state": "REPLANNING",
                  "event": {"type": "ASSIGNMENT",
                            "payload": {"assignments": [{"slot_index": 0}]}},
                  "sats": []}
    no_state_key = {"v": 1, "t": 2.0, "coverage": 0.5, "min_sep": 1.0, "sats": []}
    path = tmp_path / "schema_corrupt.jsonl"
    _write_jsonl(
        path,
        [
            json.dumps(header, sort_keys=True),
            json.dumps(dict(tick, sats=[{"id": 0, "role": "leader", "r": [0, 0, 0],
                                         "v": [0, 0, 0], "dv_used": 0.0}])),  # no status
            json.dumps(dict(tick, sats=[{"id": 0, "role": "leader", "status": "NOMINAL",
                                         "v": [0, 0, 0], "dv_used": 0.0}])),  # no r
            json.dumps(dict(tick, sats=["leader"])),  # sat row not an object
            json.dumps(dict(tick, event=["ASSIGNMENT"])),  # event not an object
            json.dumps(assignment),  # ASSIGNMENT row missing sat_id
            json.dumps(no_state_key),  # tick line without a state key
            json.dumps(tick, sort_keys=True),
        ],
    )
    log = load_jsonl(path)
    assert log.frames == [tick]
    assert log.times == [0.0]
    assert log.header == header
    assert log.skipped == 6


def test_replay_seek_index(tmp_path):
    log = load_jsonl(_times_log(tmp_path))
    assert index_at(log, -5.0) == 0  # before start -> first frame
    assert index_at(log, 0.0) == 0
    assert index_at(log, 1.0) == 1  # bisect: first frame with t >= seek
    assert index_at(log, 2.0) == 1
    assert index_at(log, 3.0) == 2
    assert index_at(log, 100.0) == 2  # past the end -> hold the last frame
    assert index_at(log, 0.0) == 0  # backwards seek is just another bisect


def test_replay_seek_index_empty_log():
    from cubesat.replay import ReplayLog

    empty = ReplayLog(frames=[], times=[], header=None, summary=None, skipped=0)
    assert index_at(empty, 42.0) == 0


def test_replay_list_empty_dir(tmp_path):
    assert list_logs(tmp_path) == []


def test_replay_list_missing_dir(tmp_path):
    assert list_logs(tmp_path / "does_not_exist") == []


def test_replay_list_sorted_jsonl_only(tmp_path):
    (tmp_path / "b.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "a.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("x\n", encoding="utf-8")
    (tmp_path / "c.json").write_text("{}\n", encoding="utf-8")
    assert list_logs(tmp_path) == ["a.jsonl", "b.jsonl"]


def _times_log(tmp_path):
    lines = []
    for t in (0.0, 2.0, 4.0):
        lines.append(json.dumps(
            {"v": 1, "t": t, "state": "NOMINAL", "coverage": 0.5, "min_sep": 1.0,
             "sats": []}, sort_keys=True))
    path = tmp_path / "times.jsonl"
    _write_jsonl(path, lines)
    return path
