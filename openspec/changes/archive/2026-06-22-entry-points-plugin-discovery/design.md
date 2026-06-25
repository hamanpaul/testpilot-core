## Context

來源設計:`docs/superpowers/specs/2026-06-18-entry-points-discovery-design.md`。現況 loader 掃 `plugins/` + sys.path hack;Hatch wheel 僅含 `src/testpilot`;`plugins/wifi_llapi/__init__.py` 有、`plugins/__init__.py` 與 brcm 的沒有。選定 B(純 entry_points + 現在 packaging)。

## Goals / Non-Goals

**Goals:**
- 發現/載入走 `entry_points`(group `testpilot.plugins`);移除 dir-scan + sys.path hack。
- in-repo plugin 正規化為 entry_point 套件;零雙軌。
- 行為位元級不變(相同 plugin 名單與 run 行為)。

**Non-Goals:**
- 不物理移出 plugin(P4);不做 versioned contract(P2b);不碰 run loop/CLI/case 格式。

## Decisions

### D1:發現/載入經 entry_points
`discover()` = `entry_points(group="testpilot.plugins")` 的 name 清單;`load(name)` = 對應 ep `.load()()`。移除 `spec_from_file_location` + sys.path 插入;保留型別檢查/快取/load_all。
- **理由**:標準 plugin 發現;第三方 pip plugin 可被發現;消除 sys.path hack 脆弱。

### D2:in-repo plugin 正規化為 package(過渡納入 testpilot wheel)
補 `__init__.py`;wifi 5 bare import → `plugins.wifi_llapi.*`;pyproject 宣告 entry_points;Hatch wheel 納入 `plugins`。
- **理由**:`ep.load()` 需正規 package import;packaging 本是 P4 必做,此處一次到位、de-risk P4。
- **替代 (b)**:各 plugin 獨立 pyproject 可安裝套件(=P4 形態)。本案採 (a) 過渡(輕),P4 轉 (b)。

### D3:檔案資源路徑由模組位置推導
plugin 的 `cases_dir`/reports/templates 路徑改由 plugin 模組檔案位置推導(`Path(module.__file__).parent` / `importlib.resources`),取代「`plugins_dir/<name>` 猜路徑」。
- **理由**:entry_point 給程式碼位置;套件化後檔案隨模組走才穩(P4 移出 repo 也成立)。

### D4:install-flow 為發現前提
dev/CI 以 `pip install -e .` 為準(entry_points 靠已安裝 dist metadata);整理 stale editable install;`realistic_runtime` 子程序測試在複製環境亦安裝。
- **理由**:entry_points 發現的必要條件;且為 P4 既定現實。

## Risks / Trade-offs

- **[發現需安裝]** → 緩解:本案納入 install-flow 整理;一次到位。
- **[行為保真]** 載入路徑改變 → 緩解:bare import 全轉 package 路徑;斷言 discover() 名單不變;golden + 全套回歸。
- **[Hatch 納入 plugins 為過渡]** → 緩解:P4 拆獨立 dist;註明過渡。
- **[realistic_runtime 測試]** 依賴複製+subprocess → 緩解:改為複製環境安裝或改測法去 sys.path 依賴。

## Migration Plan

1. 正規化 package(`__init__.py` + wifi 5 import + tests)。
2. loader 改 entry_points(discover/load),移除 dir-scan/sys.path hack;檔案資源路徑由模組位置推導。
3. pyproject entry_points + Hatch 納入 plugins;`pip install -e .`。
4. install-flow(dev/CI/realistic_runtime)。
5. 守門 + golden + 全套回歸。
- **Rollback**:單一 change revert。

## Open Questions

- 檔案資源路徑推導用 `__file__` 還是 `importlib.resources`(plan 定;傾向 `__file__.parent`,簡單且 editable/P4 皆成立)。
- realistic_runtime 改「複製環境安裝」還是「改測法」(plan 定;傾向後者,降低 CI 複雜度)。
