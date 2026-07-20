# copilot SDK 0.1.x Permission Handler 對齊 Implementation Plan

> **SUPERSEDED（2026-07-17）：** 本檔以下 checklist 與 code snippet 僅保留為 #16 的歷史執行紀錄，禁止重新執行或複製。現行契約以 `docs/superpowers/specs/2026-07-17-tier2-env-recovery-design.md` 為準：一般 per-case session 與 tool-denied tier-2 one-shot 共用 run-scoped `agent_session_degraded` marker；所有 provider/SDK/plugin callback 例外只保存 phase 與 exception type，不保存 raw exception text；tier-1 / tier-2 各自依 policy 執行，不做整場 builtin fallback。

**Goal:** session foundation 在 github-copilot-sdk 0.1.x 下可成功建立（approve-all wire shape `{"kind": "approved"}`），建立失敗時 loud surfacing（一次性 warning + run payload degraded key）。

**Architecture（歷史範圍）：** #16 當時只動 `copilot_session.py::_resolve_permission_handler`、`orchestrator._create_case_session` 與 `run_loop.run_plugin_cases`；後續 #4 已把現行架構擴充為 tier-1-first / opt-in tier-2，並以共享 degraded marker 呈現一般 session 與 tier-2 one-shot 的 SDK/provider failure。

**Tech Stack:** Python 3.11+、pytest、github-copilot-sdk 0.1.x（僅 smoke，測試全 mock）。

**參照:** spec `docs/superpowers/specs/2026-07-06-copilot-sdk-permission-drift-design.md`、openspec change `copilot-sdk-permission-alignment`、issue #16。

---

### Task 1: permission handler 對齊 0.1.x（TDD）

**Files:**
- Modify: `src/testpilot/core/copilot_session.py:194-204`
- Test: `tests/test_copilot_session.py`

- [ ] **Step 1: 改寫既有 fake SDK fixture 並新增 wire-shape RED tests**

`tests/test_copilot_session.py:123` 現行 fake 是舊 API 形狀（`SimpleNamespace(PermissionHandler=SimpleNamespace(approve_all="APPROVE_ALL"))`）。改為 0.1.x 形狀並新增測試：

```python
# 取代 L123 的 fake_sdk 定義（該測試上下文中 PermissionRequestResult 用 dict 代表 TypedDict）
fake_sdk = SimpleNamespace(
    PermissionHandler=None,  # 0.1.x 是 typing alias，getattr 拿到的不是 class
    PermissionRequestResult=dict,  # TypedDict(total=False) 在 runtime 就是 dict 工廠
)

def test_resolve_permission_handler_returns_approve_all_callable():
    manager = CopilotSessionManager(sdk_module=fake_sdk)
    handler = manager._resolve_permission_handler()
    assert callable(handler)
    result = handler(SimpleNamespace(kind="tool-use"), {"tool": "bash"})
    assert result == {"kind": "approved"}  # wire shape 精確鎖定，防 false-green

def test_resolve_permission_handler_missing_result_type_raises():
    broken_sdk = SimpleNamespace(PermissionHandler=None)  # 無 PermissionRequestResult
    manager = CopilotSessionManager(sdk_module=broken_sdk)
    with pytest.raises(CopilotSDKUnavailableError, match="copilot.PermissionRequestResult is unavailable"):
        manager._resolve_permission_handler()

def test_injected_permission_handler_wins_without_sdk_touch():
    sentinel = object()
    manager = CopilotSessionManager(sdk_module=None, permission_handler=sentinel)
    assert manager._resolve_permission_handler() is sentinel  # sdk_module=None 而不炸 = 沒碰 SDK
```

同檔既有 `create_session`/`resume_session` 測試中 `assert created_config["on_permission_request"] == "APPROVE_ALL"`（L176/L182）改為：

```python
handler = created_config["on_permission_request"]
assert handler(SimpleNamespace(), {}) == {"kind": "approved"}
```

- [ ] **Step 2: 跑測試確認 RED**

Run: `cd /home/paul_chen/prj_arc/testpilot-core/.worktrees/16-copilot-sdk-permission && .venv/bin/python -m pytest tests/test_copilot_session.py -v 2>&1 | tail -20`（無 .venv 則先 `uv venv && uv pip install -e ".[dev]"`）
Expected: 新測試 FAIL——現行實作 raise `copilot.PermissionHandler.approve_all is unavailable`。

- [ ] **Step 3: 改寫 `_resolve_permission_handler`**

```python
    def _resolve_permission_handler(self) -> Any:
        if self.permission_handler is not None:
            return self.permission_handler
        sdk = self._load_sdk()
        result_type = getattr(sdk, "PermissionRequestResult", None)
        if result_type is None:
            raise CopilotSDKUnavailableError(
                "copilot.PermissionRequestResult is unavailable"
            )

        def _approve_all(request: Any, context: Any) -> Any:
            return result_type(kind="approved")

        return _approve_all
```

註：`PermissionRequestResult` 是 `TypedDict(total=False)`，`result_type(kind="approved")` 在 runtime 等價 `{"kind": "approved"}`；test fixture 用 `dict` 代表故 assert `== {"kind": "approved"}` 成立。

- [ ] **Step 4: 跑測試確認 GREEN**

Run: 同 Step 2 指令
Expected: 全 PASS（含改寫後的 create/resume 測試）。

- [ ] **Step 5: Commit**

```bash
git add src/testpilot/core/copilot_session.py tests/test_copilot_session.py
git commit -m "fix(copilot_session): 對齊 github-copilot-sdk 0.1.x permission handler wire shape (#16)"
```

### Task 2: loud surfacing——一次性 warning + degraded 狀態（TDD）

**Files:**
- Modify: `src/testpilot/core/orchestrator.py:150-173`（`_create_case_session`）
- Test: `tests/test_orchestrator.py`（或既有 orchestrator 測試檔，執行前先 `grep -rn "_create_case_session" tests/` 確認歸屬檔案，無則新建 `tests/test_orchestrator_session_degraded.py`）

- [ ] **Step 1: RED tests——warning 恰一次 + degraded 狀態可讀**

```python
import logging
from pathlib import Path

from testpilot.core.orchestrator import Orchestrator


class _FailingSessionManager:
    def create_session(self, request):
        raise RuntimeError("boom")


def _orchestrator_with_failing_sessions() -> Orchestrator:
    # 比照 tests/test_orchestrator_retry.py:19 的既有建構方式
    orch = Orchestrator(project_root=Path(__file__).resolve().parents[1])
    orch.session_manager = _FailingSessionManager()
    return orch


def test_session_failure_warns_once_and_sets_degraded(caplog):
    orch = _orchestrator_with_failing_sessions()
    plan = {"session_id": "s1", "model": "m", "reasoning_effort": "high"}
    with caplog.at_level(logging.WARNING):
        h1 = orch._create_case_session(dict(plan))
        h2 = orch._create_case_session(dict(plan))
    assert h1["status"] == "failed" and h2["status"] == "failed"  # 既有 per-case 行為不變
    warnings = [r for r in caplog.records
                if r.levelno == logging.WARNING and "marked degraded" in r.getMessage()]
    assert len(warnings) == 1  # 一次性 loud warning
    assert orch.agent_session_degraded["degraded"] is True
    assert "RuntimeError" in orch.agent_session_degraded["reason"]
    assert "boom" not in orch.agent_session_degraded["reason"]


def test_no_failure_keeps_degraded_false():
    orch = Orchestrator(project_root=Path(__file__).resolve().parents[1])
    assert orch.agent_session_degraded == {"degraded": False, "reason": ""}
```

- [ ] **Step 2: 跑測試確認 RED**

Run: `.venv/bin/python -m pytest tests/test_orchestrator_session_degraded.py -v`
Expected: FAIL——`agent_session_degraded` 屬性不存在。

- [ ] **Step 3: 實作 orchestrator degraded 追蹤**

`_create_case_session` 修改（保留既有回傳形狀）：

```python
    # __init__（或 dataclass 欄位區）新增：
    #   self.agent_session_degraded: dict[str, Any] = {"degraded": False, "reason": ""}

    def _create_case_session(self, session_plan):
        if self.session_manager is None or CopilotSessionRequest is None:
            return None
        try:
            ...  # 既有建立邏輯不動
        except Exception as exc:
            safe_reason = f"SDK session operation failed ({type(exc).__name__})"
            if not self.agent_session_degraded["degraded"]:
                log.warning(
                    "SDK session foundation failed; agent session marked "
                    "degraded: error_type=%s",
                    type(exc).__name__,
                )
                self.agent_session_degraded = {
                    "degraded": True,
                    "reason": safe_reason,
                }
            else:
                log.debug(
                    "SDK session operation failed (already degraded): error_type=%s",
                    type(exc).__name__,
                )
            return {"status": "failed", "error": safe_reason}
```

- [ ] **Step 4: 跑測試確認 GREEN，並確認既有 orchestrator 測試不破**

Run: `.venv/bin/python -m pytest tests/ -k "orchestrator or copilot" -v 2>&1 | tail -15`
Expected: 全 PASS。

- [ ] **Step 5: Commit**

```bash
git add src/testpilot/core/orchestrator.py tests/
git commit -m "feat(orchestrator): session foundation 失敗一次性 loud warning + degraded 狀態 (#16)"
```

### Task 3: run payload 注入 `agent_session_degraded`（TDD）

**Files:**
- Modify: `src/testpilot/core/run_loop.py`（`run_plugin_cases` 尾段，`build_reports(run_result)` 返回處，現約 L368-371）
- Test: 既有 run_loop 測試檔（`grep -rln "run_plugin_cases" tests/` 定位；沿用其 fake plugin/reporter fixture）

- [ ] **Step 1: RED test**

```python
def test_run_payload_carries_agent_session_degraded(...):
    # 沿用既有 run_loop 測試的最小 fake plugin + reporter（build_reports 回傳 dict）
    payload = run_plugin_cases(orchestrator=orch, plugin_name="fake", case_ids=None)
    assert payload["agent_session_degraded"] == {"degraded": False, "reason": ""}

def test_run_payload_degraded_true_when_sessions_fail(...):
    # orch.session_manager = _FailingSessionManager()，runner 選 copilot 使 session plan 存在
    payload = run_plugin_cases(orchestrator=orch, plugin_name="fake", case_ids=None)
    assert payload["agent_session_degraded"]["degraded"] is True
    assert "RuntimeError" in payload["agent_session_degraded"]["reason"]
    assert "boom" not in payload["agent_session_degraded"]["reason"]
```

- [ ] **Step 2: 跑測試確認 RED**

Run: `.venv/bin/python -m pytest tests/ -k "run_payload" -v`
Expected: FAIL——payload 無此 key。

- [ ] **Step 3: 實作注入**

`run_loop.py` 尾段：

```python
    reporter = plugin.create_reporter()
    build_reports = getattr(reporter, "build_reports", None)
    if not callable(build_reports):
        raise RuntimeError(f"{plugin_name} reporter does not implement build_reports()")
    payload = build_reports(run_result)
    if isinstance(payload, dict):
        payload.setdefault(
            "agent_session_degraded",
            getattr(orchestrator, "agent_session_degraded", {"degraded": False, "reason": ""}),
        )
    return payload
```

- [ ] **Step 4: 跑測試確認 GREEN + 全套件**

Run: `.venv/bin/python -m pytest -q 2>&1 | tail -5`
Expected: 全綠（既知 2 個 wheel-probe env fail 除外，比照 REPO-0706 基準）。

- [ ] **Step 5: Commit**

```bash
git add src/testpilot/core/run_loop.py tests/
git commit -m "feat(run_loop): run payload 注入 agent_session_degraded key (#16)"
```

### Task 4: smoke + 收尾

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: 真 SDK smoke**

Run: `python3 -c "import sys; sys.path.insert(0,'/home/paul_chen/.local/lib/python3.12/site-packages'); sys.path.insert(0,'src'); from testpilot.core.copilot_session import CopilotSessionManager; h=CopilotSessionManager()._resolve_permission_handler(); print(h(object(), {}))"`
Expected: 印出 `{'kind': 'approved'}`，不 raise。

- [ ] **Step 2: CHANGELOG entry**

`CHANGELOG.md` `[Unreleased]` 下新增：

```markdown
### Fixed
- copilot session foundation 對齊 github-copilot-sdk 0.1.x（`PermissionHandler.approve_all` 已不存在）：自組 approve-all permission handler（wire shape `{"kind": "approved"}`）；session 建立失敗改為一次性 loud warning + run payload `agent_session_degraded` key，並只保存穩定 exception type（#16）
```

- [ ] **Step 3: 最終驗證 + Commit**

Run: `.venv/bin/python -m pytest -q 2>&1 | tail -3`
Expected: 綠。

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): #16 copilot SDK 對齊 entry"
```

- [ ] **Step 4: openspec tasks 勾選同步**

`openspec/changes/copilot-sdk-permission-alignment/tasks.md` 對應項打勾後隨最終 commit 一併提交。

---

## 驗收（PR 前）

- [ ] `pytest -q` 全綠；smoke 印出 `{'kind': 'approved'}`
- [ ] `python3 -m policy_check --repo .` 無 failure（core repo 有此 gate 時）
- [ ] PR body `Closes #16`；R-18 評估（內部行為修復，預期上 `policy-exempt:docs-sync`）
- [ ] 真機驗證（下輪 wifi_llapi run 的 agent_trace `session_handle.status == "created"`）記入 PR「後續驗證」段，不 block merge
