from testpilot.core.orchestrator import Orchestrator


def test_skeleton_descriptor_is_unsupported_execution_path():
    assert callable(Orchestrator._skeleton_run)
    # Skeleton/custom paths must expose the stable status without invoking core analysis.
    assert "unsupported_execution_path" in Orchestrator._skeleton_run.__code__.co_consts
