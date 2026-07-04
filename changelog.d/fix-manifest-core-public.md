---
type: fix
scope: install
---
install-manifest.yaml 的 `core.private` 由 `true` 更正為 `false`，對齊 `hamanpaul/testpilot-core` 實際為 public repo（serialwrap 亦 public 且標記正確；wifi_llapi/brcm_fw_upgrade 維持 private）。此欄位為 registry 標記、install.sh/build-bundle.sh 皆未讀取，故無行為變更，僅修正誤導的 metadata。
