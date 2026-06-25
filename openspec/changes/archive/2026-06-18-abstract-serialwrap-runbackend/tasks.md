## 1. RED — 介面契約 + 守門測試先紅

- [x] 1.1 新增 `RunBackend` 契約測試:斷言介面有 `setup_run`/`bind_sessions`/`mark_position`/`export_logs`/`teardown_run`,`SerialwrapBackend` 實作之、`DirectTtyBackend` 存在(stub)
- [x] 1.2 擴充守門:斷言 `src/testpilot/core` 與 `src/testpilot/reporting`(排除 backend 模組)不再具名 serialwrap/log_capture/wal
- [x] 1.3 執行確認因 `RunBackend`/`SerialwrapBackend` 未存在 + core/reporting 仍具名 serialwrap 而紅(理由正確),擷取 RED

## 2. GREEN — RunBackend 介面 + 中性 dataclass

- [x] 2.1 新增 `src/testpilot/runtime/run_backend.py`:`RunBackend` ABC + `RunHandle`/`ExportRequest`/`ExportResult` 中性 dataclass(無 serialwrap 具名)
- [x] 2.2 跑 1.1 介面存在性斷言至綠(介面部分)

## 3. GREEN — SerialwrapBackend(verbatim 收 serialwrap 邏輯)

- [x] 3.1 新增 `SerialwrapBackend`:把現 `reporting/log_capture.py` 的 daemon/WAL/decode/seq 邏輯與 orchestrator 三方法 body **verbatim 移入**(或保留 log_capture 為 backend 私有 helper、只由 backend import)
- [x] 3.2 behavior→serialwrap 指令以宣告式對照表表達,作為命名契約錨點;實際把指令記入 trace deferred(本 change 不做,以維持既有 trace 位元級不變)
- [x] 3.3 新增 `DirectTtyBackend` stub(NotImplemented,鎖介面形狀)

## 4. GREEN — 取用點改寫(去 serialwrap 具名)

- [x] 4.1 `orchestrator`:`__init__` 依 testbed config 取得 `RunBackend`(預設 serialwrap);`_start_serialwrap_for_run`/`_export_serialwrap_logs`/`_stop_serialwrap` 改呼叫 `self.run_backend.*`
- [x] 4.2 移除 `core`/`reporting`(除 backend)對 serialwrap/log_capture 的具名 import
- [x] 4.3 跑守門斷言(core/reporting 不具名 serialwrap)至綠

## 5. 回歸驗證 — 行為位元級不變

- [x] 5.1 既有 serialwrap/log_capture 測試全綠(`tests/test_log_capture.py` 等)
- [x] 5.2 golden 報表測試全綠(`dut_log_lines`/`sta_log_lines` 行範圍不變)
- [x] 5.3 全套 `pytest` 綠,無回歸
- [x] 5.4 grep 確認 `core`/`reporting`(除 backend)serialwrap 具名歸零

## 6. 收尾(workflow 後段)

- [x] 6.1 requesting-code-review(多視角:行為保真 / 抽象正確 / 契約純淨)
- [x] 6.2 依 review 修正並 re-review 至無 Critical/Important
- [x] 6.3 openspec archive → policy → conventional commit → push → PR(feature/<slug> + closing keyword,R-12/R-17)
