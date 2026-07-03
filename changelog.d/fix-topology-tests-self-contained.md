---
type: fix
scope: test
---
test_topology.py 改用 pytest fixture 於 tmp_path 寫入最小 testbed.yaml，不再依賴 git-ignored 的 configs/testbed.yaml（原本僅 CI bootstrap step 會產生），fresh clone 直接 pytest 不再有 2 個 failure。四項斷言不變（name=lab-bench-1、DUT 裝置、SSID_5G→testpilot5G、未知變數原樣保留）；inline testbed 僅含 name/DUT/SSID 不含任何 KEY 憑證，維持 R-21 機密掃描潔淨。
