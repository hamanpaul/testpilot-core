---
type: fix
scope: install
---
build-bundle.sh 的 third-party 依賴改為依已下載的 first-party wheel（core + 選定 plugins + serialwrap）metadata 解析閉包，取代原本手列套件名裸抓最新版——後者會抓到違反 core `click>=8.1,<8.4` pin 的 click 8.4.x，使 dry-run gate 以 ResolutionImpossible 失敗、產不出 bundle。新增 regression 測試鎖定此契約。
