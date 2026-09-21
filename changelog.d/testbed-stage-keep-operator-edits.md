---
type: fix
scope: core
---
`stage_plugin_testbed()` 不再每次執行都用 plugin 的 `testbed.yaml.example` 覆蓋 `configs/testbed.yaml`：staged 檔案第一行帶 `# testpilot: staged from plugin '<name>'` 標記，同一 plugin 再跑時保留 operator 的編輯（bench 專屬 `variables`、`station_driver` 等），只有缺檔、換 plugin 或舊版無標記檔才重新 staging。先前的無條件覆蓋讓 README 所說「Edit `configs/testbed.yaml` to match your lab」實際上不成立（2026-09-17 EIT bench：改好的 `STA_IP`/`DUT_LAN_IP` 每次被模板值蓋掉，流量刺激打到錯的主機）。
