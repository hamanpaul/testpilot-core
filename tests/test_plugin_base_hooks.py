from plugins._template.plugin import Plugin


class _FakeSubparsers:
    def add_parser(self, *a, **k):
        raise AssertionError("default register_cli must not register anything")


def test_default_validate_case_is_noop():
    assert Plugin().validate_case({"id": "x"}) is None


def test_default_execution_policy_is_neutral():
    assert Plugin().execution_policy({"id": "x"}) == {}


def test_default_register_cli_is_noop():
    # default must not touch the registrar
    assert Plugin().register_cli(_FakeSubparsers()) is None
