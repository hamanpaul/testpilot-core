from testpilot_sample_echo.plugin import EchoRunner, Plugin


def test_plugin_contract_shape():
    plugin = Plugin()
    assert plugin.name == "sample_echo"
    assert plugin.api_version == "1.0"


def test_discovers_exactly_one_case():
    # load_cases_dir 非 fail-fast(壞檔靜默略過),故明確斷言數量,避免假綠
    cases = Plugin().discover_cases()
    assert len(cases) == 1
    assert cases[0]["id"] == "echo-hello"


def test_run_pipeline_yields_pass():
    plugin = Plugin()
    case = plugin.discover_cases()[0]
    outcome = plugin.run_pipeline(case, topology=case.get("topology"))
    assert outcome["verdict"] is True


def test_runner_reports_pass():
    runner = Plugin().create_runner()
    result = runner.run(None, "sample_echo", None, None, None)
    assert result["overall"] == "PASS"
    assert result["results"][0]["case_id"] == "echo-hello"
