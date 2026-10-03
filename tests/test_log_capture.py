"""Tests for testpilot.runtime._serialwrap_log (log capture backend helper)."""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from testpilot.runtime import _serialwrap_log as log_capture


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _set_serialwrap_bin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure SERIALWRAP_BIN env var is set for all log_capture tests."""
    monkeypatch.setenv("SERIALWRAP_BIN", "/tmp/serialwrap")


def _make_record(
    seq: int,
    com: str = "COM0",
    text: str = "hello\n",
    direction: str = "RX",
    cmd_id: str | None = None,
) -> dict:
    return {
        "seq": seq,
        "com": com,
        "dir": direction,
        "payload_b64": base64.b64encode(text.encode()).decode(),
        "cmd_id": cmd_id,
        "wall_ts": "2026-03-26T07:00:00+00:00",
        "mono_ts_ns": 1000000 * seq,
    }


SAMPLE_RECORDS = [
    _make_record(1, "COM0", "line1_dut\n"),
    _make_record(2, "COM1", "line1_sta\n"),
    _make_record(3, "COM0", "line2_dut\nline3_dut\n"),
    _make_record(4, "COM1", "line2_sta\n"),
    _make_record(5, "COM0", "line4_dut\n", cmd_id="cmd_abc"),
]


# ---------------------------------------------------------------------------
# decode_log
# ---------------------------------------------------------------------------

class TestDecodeLog:
    def test_all_records(self):
        text = log_capture.decode_log(SAMPLE_RECORDS)
        assert "line1_dut" in text
        assert "line1_sta" in text
        assert "line4_dut" in text

    def test_com_filter(self):
        text = log_capture.decode_log(SAMPLE_RECORDS, com_filter="COM0")
        assert "line1_dut" in text
        assert "line2_dut" in text
        assert "line4_dut" in text
        assert "sta" not in text

    def test_com_filter_sta(self):
        text = log_capture.decode_log(SAMPLE_RECORDS, com_filter="COM1")
        assert "line1_sta" in text
        assert "line2_sta" in text
        assert "dut" not in text

    def test_empty_records(self):
        assert log_capture.decode_log([]) == ""

    def test_bad_base64_skipped(self):
        records = [{"seq": 1, "com": "COM0", "payload_b64": "!!!invalid!!!"}]
        assert log_capture.decode_log(records) == ""

    def test_missing_payload(self):
        records = [{"seq": 1, "com": "COM0"}]
        assert log_capture.decode_log(records) == ""


# ---------------------------------------------------------------------------
# build_seq_to_line_map
# ---------------------------------------------------------------------------

class TestBuildSeqToLineMap:
    def test_basic_mapping(self):
        mapping = log_capture.build_seq_to_line_map(SAMPLE_RECORDS, com_filter="COM0")
        assert mapping[1] == 1  # "line1_dut\n" → line 1
        assert mapping[3] == 2  # "line2_dut\nline3_dut\n" → line 2
        assert mapping[5] == 4  # "line4_dut\n" → line 4

    def test_sta_mapping(self):
        mapping = log_capture.build_seq_to_line_map(SAMPLE_RECORDS, com_filter="COM1")
        assert mapping[2] == 1  # "line1_sta\n" → line 1
        assert mapping[4] == 2  # "line2_sta\n" → line 2

    def test_no_filter(self):
        mapping = log_capture.build_seq_to_line_map(SAMPLE_RECORDS)
        assert 1 in mapping
        assert 2 in mapping
        assert 5 in mapping

    def test_empty_records(self):
        assert log_capture.build_seq_to_line_map([]) == {}

    def test_multiline_record_maps_to_first_line(self):
        records = [_make_record(10, "COM0", "a\nb\nc\n")]
        mapping = log_capture.build_seq_to_line_map(records, com_filter="COM0")
        assert mapping[10] == 1

    def test_fragments_map_to_lines_in_concatenated_log(self):
        records = [
            _make_record(1, "COM0", "first"),
            _make_record(2, "COM0", "-second\nthird"),
            _make_record(3, "COM0", "-fourth\n"),
        ]

        assert log_capture.decode_log(records, com_filter="COM0") == (
            "first-second\nthird-fourth\n"
        )
        assert log_capture.build_seq_to_line_map(records, com_filter="COM0") == {
            1: 1,
            2: 1,
            3: 2,
        }

    def test_line_spans_include_multiline_end_record(self):
        records = [
            _make_record(10, "COM0", "start\n"),
            _make_record(11, "COM0", "end-a\nend-b\nend-c\n"),
        ]

        spans = log_capture.build_seq_to_line_span_map(records, com_filter="COM0")

        assert spans == {10: (1, 1), 11: (2, 4)}
        assert log_capture.seq_range_to_line_range(10, 11, spans) == "L1-L4"

    def test_line_spans_follow_global_crlf_boundary_across_records(self):
        records = [
            _make_record(1, "COM0", "a\r"),
            _make_record(2, "COM0", "\nb\n"),
        ]

        assert log_capture.decode_log(records, com_filter="COM0").splitlines() == [
            "a",
            "b",
        ]
        assert log_capture.build_seq_to_line_span_map(records, com_filter="COM0") == {
            1: (1, 1),
            2: (1, 2),
        }

    def test_line_spans_are_independent_per_com_and_skip_invalid_payload(self):
        records = [
            _make_record(1, "COM0", "dut-first"),
            _make_record(2, "COM1", "sta-first\n"),
            {"seq": 3, "com": "COM0", "payload_b64": "%%%not-base64%%%"},
            _make_record(4, "COM0", "-dut-last\n"),
            _make_record(5, "COM1", "sta-second\nsta-third\n"),
        ]

        dut_spans = log_capture.build_seq_to_line_span_map(records, com_filter="COM0")
        sta_spans = log_capture.build_seq_to_line_span_map(records, com_filter="COM1")

        assert log_capture.decode_log(records, com_filter="COM0") == "dut-first-dut-last\n"
        assert dut_spans == {1: (1, 1), 4: (1, 1)}
        assert sta_spans == {2: (1, 1), 5: (2, 3)}
        assert log_capture.seq_range_to_line_range(1, 4, dut_spans) == "L1-L1"
        assert log_capture.seq_range_to_line_range(1, 5, sta_spans) == "L1-L3"


# ---------------------------------------------------------------------------
# seq_range_to_line_range
# ---------------------------------------------------------------------------

class TestSeqRangeToLineRange:
    def test_exact_match(self):
        seq_map = {1: 1, 3: 2, 5: 4}
        assert log_capture.seq_range_to_line_range(1, 5, seq_map) == "L1-L4"

    def test_approximate_match(self):
        seq_map = {1: 1, 3: 2, 5: 4}
        # seq 2 doesn't exist; nearest >= 2 is 3 (line 2)
        # seq 4 doesn't exist; nearest <= 4 is 3 (line 2)
        assert log_capture.seq_range_to_line_range(2, 4, seq_map) == "L2-L2"

    def test_none_start(self):
        assert log_capture.seq_range_to_line_range(None, 5, {1: 1}) == ""

    def test_none_end(self):
        assert log_capture.seq_range_to_line_range(1, None, {1: 1}) == ""

    def test_empty_map(self):
        assert log_capture.seq_range_to_line_range(1, 5, {}) == ""

    def test_no_matching_seqs(self):
        seq_map = {10: 1, 20: 2}
        assert log_capture.seq_range_to_line_range(30, 40, seq_map) == ""

    def test_cross_com_records_outside_case_interval_do_not_supply_lines(self):
        records = [
            _make_record(5, "COM1", "sta-before\n"),
            _make_record(10, "COM0", "dut-case-start\n"),
            _make_record(20, "COM0", "dut-case-end\n"),
            _make_record(25, "COM1", "sta-after\n"),
        ]

        sta_spans = log_capture.build_seq_to_line_span_map(records, com_filter="COM1")
        sta_start_lines = log_capture.build_seq_to_line_map(records, com_filter="COM1")

        assert log_capture.seq_range_to_line_range(10, 20, sta_spans) == ""
        assert log_capture.seq_range_to_line_range(10, 20, sta_start_lines) == ""

    def test_approximate_match_stays_inside_requested_interval(self):
        span_map = {5: (1, 2), 12: (3, 4), 18: (5, 7), 25: (8, 9)}
        int_map = {5: 1, 12: 3, 18: 5, 25: 8}

        assert log_capture.seq_range_to_line_range(10, 20, span_map) == "L3-L7"
        assert log_capture.seq_range_to_line_range(10, 20, int_map) == "L3-L5"

    @pytest.mark.parametrize(
        "seq_map",
        [
            {10: (1, 3), 20: (4, 6)},
            {10: 1, 20: 4},
        ],
    )
    def test_reversed_sequence_interval_fails_closed(self, seq_map):
        assert log_capture.seq_range_to_line_range(20, 10, seq_map) == ""


# ---------------------------------------------------------------------------
# save_decoded_log
# ---------------------------------------------------------------------------

class TestSaveDecodedLog:
    def test_creates_file(self, tmp_path: Path):
        out = tmp_path / "subdir" / "test.log"
        result = log_capture.save_decoded_log("hello world\n", out)
        assert result == out
        assert out.read_text() == "hello world\n"

    def test_preserves_exact_utf8_newline_bytes_on_windows(
        self, tmp_path: Path, monkeypatch, caplog
    ):
        original_io_open = io.open

        def windows_text_output_open(
            file,
            mode="r",
            buffering=-1,
            encoding=None,
            errors=None,
            newline=None,
            closefd=True,
            opener=None,
        ):
            if "b" not in mode and "w" in mode and newline is None:
                newline = "\r\n"
            return original_io_open(
                file,
                mode,
                buffering,
                encoding,
                errors,
                newline,
                closefd,
                opener,
            )

        monkeypatch.setattr(io, "open", windows_text_output_open)
        caplog.set_level(20, logger=log_capture.logger.name)
        text = "β\r\nlast\n"
        expected = text.encode("utf-8")
        out = tmp_path / "DUT.log"

        result = log_capture.save_decoded_log(text, out)

        assert result.read_bytes() == expected
        assert f"({len(expected)} bytes)" in caplog.text


# ---------------------------------------------------------------------------
# get_current_seq
# ---------------------------------------------------------------------------

class TestGetCurrentSeq:
    def test_reads_last_line(self, tmp_path: Path):
        wal = tmp_path / "raw.wal.ndjson"
        records = [
            json.dumps({"seq": 100, "com": "COM0", "payload_b64": "dGVzdA=="}),
            json.dumps({"seq": 200, "com": "COM1", "payload_b64": "dGVzdA=="}),
        ]
        wal.write_text("\n".join(records) + "\n")
        assert log_capture.get_current_seq(wal, same_host_wal_path=True) == 200

    def test_empty_file(self, tmp_path: Path):
        wal = tmp_path / "empty.ndjson"
        wal.write_text("")
        assert log_capture.get_current_seq(wal, same_host_wal_path=True) is None

    def test_missing_file(self, tmp_path: Path):
        assert log_capture.get_current_seq(
            tmp_path / "nonexistent.ndjson", same_host_wal_path=True
        ) is None


# ---------------------------------------------------------------------------
# Daemon lifecycle (mocked)
# ---------------------------------------------------------------------------

class TestDaemonLifecycle:
    @patch("testpilot.runtime._serialwrap_log._run_sw")
    def test_start_daemon(self, mock_run):
        mock_run.return_value = {"ok": True, "pid": 12345, "wal_path": "/tmp/serialwrap/wal/raw.wal.ndjson"}
        result = log_capture.start_daemon()
        assert result["pid"] == 12345
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args[:2] == ["daemon", "start"]

    @patch("testpilot.runtime._serialwrap_log._run_sw")
    def test_start_daemon_with_profile_dir(self, mock_run):
        mock_run.return_value = {"ok": True, "pid": 99}
        log_capture.start_daemon(profile_dir="/custom/profiles")
        call_args = mock_run.call_args[0][0]
        assert "--profile-dir" in call_args
        assert "/custom/profiles" in call_args

    @patch("testpilot.runtime._serialwrap_log._run_sw")
    def test_stop_daemon(self, mock_run):
        mock_run.return_value = {"ok": True, "stopping": True}
        log_capture.stop_daemon()
        mock_run.assert_called_once()

    @patch("testpilot.runtime._serialwrap_log._run_sw", side_effect=RuntimeError("not running"))
    def test_stop_daemon_ignores_error(self, mock_run):
        log_capture.stop_daemon()  # should not raise

    @patch("testpilot.runtime._serialwrap_log._run_sw")
    @patch("testpilot.runtime._serialwrap_log.subprocess.Popen")
    def test_setup_sessions(self, mock_popen, mock_run):
        # _run_sw handles: device list (1st call), alias set (subsequent)
        mock_run.side_effect = [
            # device list call
            {"ok": True, "devices": [
                {"by_id": "/dev/serial/by-id/dev0", "real_path": "/dev/ttyUSB0"},
                {"by_id": "/dev/serial/by-id/dev1", "real_path": "/dev/ttyUSB1"},
            ]},
            # alias dut
            {"ok": True, "alias": "dut"},
            # alias sta
            {"ok": True, "alias": "sta"},
        ]
        # Popen handles: bind calls (return immediately)
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ('{"ok":true}', "")
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        devices = [
            {"profile": "prpl-template", "com": "COM0", "alias": "dut",
             "serial_port": "/dev/ttyUSB0"},
            {"profile": "prpl-template", "com": "COM1", "alias": "sta",
             "serial_port": "/dev/ttyUSB1"},
        ]
        log_capture.setup_sessions(devices, bind_timeout=5)
        # 2 Popen bind calls
        assert mock_popen.call_count == 2
        # 1 device list + 2 alias = 3 _run_sw calls
        assert mock_run.call_count == 3


# ---------------------------------------------------------------------------
# export_records (mocked)
# ---------------------------------------------------------------------------

class TestExportRecords:
    @patch("testpilot.runtime._serialwrap_log._run_sw")
    def test_basic_export(self, mock_run):
        mock_run.return_value = {"ok": True, "records": SAMPLE_RECORDS}
        result = log_capture.export_records(from_seq=1, to_seq=100)
        assert len(result) == 5
        call_args = mock_run.call_args[0][0]
        assert "--from-seq" in call_args
        assert "--to-seq" in call_args

    @patch("testpilot.runtime._serialwrap_log._run_sw")
    def test_export_without_to_seq(self, mock_run):
        mock_run.side_effect = [
            {"ok": True, "seq": 10},
            {"ok": True, "records": []},
        ]
        log_capture.export_records(from_seq=1)
        call_args = mock_run.call_args[0][0]
        assert "--from-seq" in call_args
        assert call_args[call_args.index("--to-seq") + 1] == "10"
        assert call_args[call_args.index("--limit") + 1] == "1000"

    @patch("testpilot.runtime._serialwrap_log._run_sw")
    def test_export_with_unlimited_limit(self, mock_run):
        mock_run.return_value = {"ok": True, "records": []}
        log_capture.export_records(from_seq=10, to_seq=200, limit=0)
        call_args = mock_run.call_args[0][0]
        assert call_args == [
            "wal",
            "export",
            "--from-seq",
            "10",
            "--to-seq",
            "200",
            "--limit",
            "1000",
        ]

    @patch("testpilot.runtime._serialwrap_log._run_sw")
    def test_export_missing_records(self, mock_run):
        mock_run.side_effect = [
            {"ok": True, "seq": 10},
            {"ok": True},
        ]
        result = log_capture.export_records(from_seq=1)
        assert result == []


# ---------------------------------------------------------------------------
# Integration: decode → save → map → line range
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_full_flow(self, tmp_path: Path):
        records = SAMPLE_RECORDS

        # Decode DUT log
        dut_text = log_capture.decode_log(records, com_filter="COM0")
        dut_log = log_capture.save_decoded_log(dut_text, tmp_path / "DUT.log")
        assert dut_log.exists()

        # Build DUT seq→line map
        dut_map = log_capture.build_seq_to_line_map(records, com_filter="COM0")
        assert dut_map[1] == 1
        assert dut_map[3] == 2
        assert dut_map[5] == 4

        # Convert seq range for a case that ran from seq 1 to seq 5
        line_range = log_capture.seq_range_to_line_range(1, 5, dut_map)
        assert line_range == "L1-L4"

        # Verify log content
        content = dut_log.read_text()
        assert "line1_dut" in content
        assert "line4_dut" in content
        assert "sta" not in content
