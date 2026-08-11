---
type: change
scope: docs
---

- 調整 TestPilot Core 的公開定位與說明：README、package metadata、CLI help 與 SDK docstring 改以「plugin-based test automation and verification framework」描述，不再把 Core 限定為 embedded-only；同時保留目前主要實績仍集中於 embedded / real-hardware verification、其他 domain 需要自行開發與驗證 Plugin integration 的限制。並同步修正 release-flow 中已過時的 static-version / metadata-only release 敘述，使其對齊現行 dynamic version、GitHub Release wheel 與 managed-install 行為。
