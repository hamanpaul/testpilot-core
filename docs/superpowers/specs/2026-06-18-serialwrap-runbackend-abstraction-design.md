# Phase 3 (B1): serialwrap → RunBackend 抽象 — 設計 spec

> 制定日期:2026-06-18
> 狀態:草案(brainstorm 已定調,待 review)
> MOC:`docs/superpowers/plugin-sdk-decoupling-MOC.md`
> 母 spec:`docs/superpowers/specs/2026-06-17-testpilot-plugin-sdk-design.md`
> 前置:Phase 1(公開層, PR #75)、Phase 2(reporter↔execution, PR #77)

## Goal

把 testpilot 對 **serialwrap 的 run-level 綁定**抽到一個可換的 `RunBackend` provider 介面後:`core/orchestrator` 與 `reporting/log_capture` 不再具名 serialwrap,serialwrap 變成預設 provider,direct-ttyUSB 等後端可日後插入。行為位元級不變。

這落實使用者對 testpilot 的**自由原則**:testpilot 不該與 serialwrap 綁死。

## Motivation(量測結論)

serialwrap 是**雙層耦合**:

- **命令執行層**:已抽象。`Transport.execute(cmd) -> result` + `transport.factory.create_transport({serialwrap|serial|adb|ssh|network|stub})`。case YAML 已是行為層(如 `ubus-cli "..."`),serialwrap 包裝整段在 transport——**這層不需動**。
- **run-level daemon + WAL 日誌層**:**未抽象、寫死**。`orchestrator`(33 觸點:`_start_serialwrap_for_run`/`_stop_serialwrap`/`_export_serialwrap_logs`)+ `reporting/log_capture.py`(23 觸點,整檔是 serialwrap RPC client + WAL 解碼 + seq→行號)。報表的 `dut_log_lines`/`sta_log_lines`(每-case 精準日誌行範圍)依賴 serialwrap WAL seq。**這層是要抽的對象。**

serialwrap 之所以是 daemon 而非單純 transport,因它解決:多寫者仲裁(agent + console 共用 UART)、RAW WAL 日誌(報表 seq→行範圍)、裝置發現/session 綁定(DUT/STA COM)。

## Scope

- 引入 `RunBackend` provider 介面(run-level lifecycle + log capture 一體)。
- `SerialwrapBackend` = 預設 impl,沿用現有 serialwrap 邏輯;behavior→command 以**宣告式表**表達(serialwrap CLI 改→改表不改碼)。
- `orchestrator` 與 `log_capture` 改寫到 `RunBackend` 介面後;core run-level 程式碼**不再具名 serialwrap**。
- 行為(CLI UX、報表輸出含日誌行範圍)**位元級不變**(serialwrap 仍預設)。

## Non-goals

- **不**把 run loop 上移進 core(那是 Phase 4;本 phase 迴圈**位置不動**,只把它對 serialwrap 的呼叫換成對 `RunBackend` 的呼叫)。
- **不**實作 `DirectTtyBackend`(僅預留介面;真有需求再做)。
- **不**動命令執行層 `Transport`(已抽象)。
- **不**改 case YAML / case 格式 / 報表內容。
- **不**碰 entry_points(P5)/CLI(P6)/物理切出(P7)。

## Architecture

### 介面層次(兩個介面,各自內聚)

```
Transport (命令層, 已有, 不動)
    execute(cmd) -> result            # serialwrap/adb/ssh/network/stub

RunBackend (run-level, 新)            # lifecycle + log capture 一體
    setup_run()        -> RunHandle   # 確保後端就緒、重設日誌位點;回傳 wal/handle
    bind_sessions(devices)            # DUT/STA COM 綁定
    mark_position()    -> int | None  # 目前日誌 seq(per-case seq_before/after 用)
    export_logs(req)   -> ExportResult# 解碼 + 存檔 + 每-case seq→行範圍
    teardown_run()                    # 結束清理(serialwrap 預設 keep-alive 供 console 併存)
  ├ SerialwrapBackend (預設)          # 用宣告式 command 表 realize 上述行為
  └ DirectTtyBackend  (介面預留)      # 日後:pyserial + tee 檔
```

### 行為 → 現有 serialwrap 函式的歸併(realization map)

| RunBackend 行為 | SerialwrapBackend 內部(現 log_capture / orchestrator) |
|---|---|
| `setup_run` | `configure` + `daemon_status`/`start_daemon` + `clean_wal`/`wal_reset` + `get_wal_path`(= 現 `_start_serialwrap_for_run`) |
| `bind_sessions` | `setup_sessions(devices)` |
| `mark_position` | `get_current_seq` / `wal_current_seq` |
| `export_logs` | `export_records` + `decode_log` + `save_decoded_log` + `build_seq_to_line_map` + `seq_range_to_line_range`(= 現 `_export_serialwrap_logs`) |
| `teardown_run` | 現 `_stop_serialwrap`(keep-alive 政策) |

> `RunHandle` / `ExportResult` / `ExportRequest` 為中性 dataclass(無 serialwrap 具名),承載 wal_path、seq、log paths、per-case 行範圍。

### 取用點改寫

- `orchestrator`:`__init__` 取得 `RunBackend`(由 testbed config 選 provider,預設 serialwrap);`_start_serialwrap_for_run`/`_export_serialwrap_logs`/`_stop_serialwrap` 改為呼叫 `self.run_backend.setup_run()/export_logs()/teardown_run()`。方法可保留為薄 wrapper 或直接內聯。
- `reporting/log_capture.py`:其 serialwrap 具體實作**移入** `SerialwrapBackend`(或 backend 內部沿用此模組,但只由 `SerialwrapBackend` import)。core/reporting 其餘程式碼不再直接 import `log_capture`。
- provider 選擇:`transport`/testbed config 既有 selector 機制延伸——`run_backend` 種類預設 `"serialwrap"`。

### 可追溯

`SerialwrapBackend` 在 realize 行為時把「行為 → 實際 serialwrap 指令」記入既有 trace(沿用現 `executed_test_command`/trace 機制),case 不需攜帶指令。

## Risks / Trade-offs

- **[行為變動(最大)]** 56 觸點(orchestrator 33 + log_capture 23)改寫,易引入差異,尤其報表日誌行範圍。→ 緩解:serialwrap 邏輯**verbatim 移入** backend、不改演算;既有 golden/report/log_capture 測試把關;先紅後綠。
- **[介面顆粒過粗/過細]** `RunBackend` 行為集若選錯,Phase 4 與 ttyUSB 會痛。→ 緩解:行為集 = 現 orchestrator 三方法(start/export/stop)+ bind + mark 的自然邊界,已對齊真實使用。
- **[provider 選擇機制]** 與既有 transport selector 的一致性。→ 緩解:沿用 testbed config selector 模式,預設 serialwrap。

## Migration Plan

1. 定義 `RunBackend` 介面 + 中性 dataclass(`RunHandle`/`ExportRequest`/`ExportResult`)。
2. 實作 `SerialwrapBackend`:把現 `log_capture` serialwrap 邏輯 + orchestrator 三方法的 body verbatim 收進來,behavior→command 用宣告式表。
3. orchestrator/reporting 改呼叫 `RunBackend`;移除 core/reporting 對 serialwrap 的具名 import。
4. provider 選擇(預設 serialwrap)。
5. 守門擴充:斷言 `core`/`reporting`(除 backend 模組)不具名 serialwrap;golden + 全套回歸。
- **Rollback**:單一 change,revert 即可;serialwrap 邏輯只是換位置未改演算。

## Open Questions

- `RunBackend` 放置位置:`src/testpilot/runtime/`? `src/testpilot/backend/`? 或 `transport/` 旁。(plan 階段定;傾向新 `src/testpilot/runtime/`,與 transport 平行)
- `log_capture.py` 是整檔移入 backend,還是保留為 `SerialwrapBackend` 的私有 helper 模組(只由 backend import)。(plan 階段定;後者改動較小)
- DirectTtyBackend 介面預留要不要附一個 stub/NotImplemented 骨架以鎖介面形狀。(傾向附 stub + 介面測試)
