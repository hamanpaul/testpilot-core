## 1. sample 本體
- [x] 1.1 `examples/sample_echo/` 套件骨架 + pyproject + entry-point + package data
- [x] 1.2 `Plugin(PluginBase)` + `EchoRunner`(run_pipeline → verdict)
- [x] 1.3 schema-valid `cases/echo-hello.yaml` + `testbed.yaml.example`
- [x] 1.4 行為 smoke 測試(discover=1、verdict Pass)

## 2. 發現與 CLI
- [x] 2.1 CI 真實安裝發現 smoke(list-plugins/list-cases/run)
- [x] 2.2 `register_cli` demo 子命令 + 測試

## 3. 守門與文件
- [x] 3.1 sample 專屬 API 邊界測試
- [x] 3.2 sample README + dev-guide 死連結/Runnable sample + README 連結
- [x] 3.3 清 `plugins/wifi_llapi/reports/` 殘骸
