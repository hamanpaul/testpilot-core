# BRCM Firmware Upgrade Plugin Design

## Problem

TestPilot 目前沒有一個可重用的 plugin 能把 Broadcom / BRCM 平台的 firmware upgrade flow 以 YAML 驅動方式表達出來。這次已經手動驗證過一條 BGW720 prpl upgrade 流程：本機 artifact 驗證、DUT/STA 傳檔、STA 先刷、確認成功後再刷 DUT、逐步執行 `cd /tmp` → `bcm_flasher $FW_NAME` → `bcm_bootstate 1` → `reboot`，並用 `/proc/version`、`bcm_bootstate`、MD5 和 serialwrap log 片段確認結果。

新 plugin 需要把這條 flow 抽成可維護、可擴充、可 headless 執行的 BRCM 家族升級框架，第一個落地 profile 是 BGW720，後續可分為 `prpl` 與 `pure_bdk` 兩類平台。

## Goals

1. 建立一個新的 `brcm_fw_upgrade` plugin，從 `plugins/_template/` 衍生，但設計成 **BRCM 家族可重用**。
2. 將以下內容盡量外部變數化，而不是寫死在 Python 中：
   - 平台 profile
   - image path / image pair
   - 拓樸（single DUT、DUT+STA）
   - transport / login / transfer capability
   - upgrade steps
   - verifier commands
   - pass / fail success gates
3. 支援 **headless 參數** 把 fw path 與其他 run-time 變數下進 upgrade flow。
4. 把 **serialwrap DUT/STA log 片段** 納入一級 evidence，讓每次升級都有可追溯證據鏈。
5. 第一版以 BGW720 為目標，並用以下兩個 image 做交互升級 acceptance：
   - `/home/build20/BGW720-0410-VERIFY/targets/BGW720-300/bcmBGW720-300_squashfs_full_update.pkgtb`
   - `/home/build20/BGW720-0403-PATCH/targets/BGW720-300/bcmBGW720-300_squashfs_full_update.pkgtb`

## Non-Goals

1. 第一版不追求 vendor-neutral 的通用 firmware upgrade framework。
2. 第一版不處理非 BRCM 平台。
3. 第一版不把所有 transfer 方法都做到完美抽象；只需要保留能力檢查與 fallback slot。
4. 第一版不要求所有 pure BDK 路徑都能 live 驗證，但資料模型必須預留。

## Design Decisions

### 1. Plugin scope

新 plugin 名稱為 `brcm_fw_upgrade`，定位是 **BRCM family reusable plugin**。BGW720 是第一個 profile，而不是唯一平台。

### 2. Platform split

平台 profile 依執行環境至少分成兩類：

- `prpl`
- `pure_bdk`

兩者的差異不應散落在 plugin 主流程裡，而應集中在 profile/baseline：

- login 前置需求
- 是否有 `scp`
- 是否有 `md5sum`
- 是否有 `bcm_bootstate`
- verifier commands 與 parsing 規則
- reboot 後 ready probe

### 3. Success model

成功條件採 **兩層式設計**：

1. **case 層**：宣告最終 success gates
2. **profile/baseline 層**：定義實際 verifier commands 與 parsing rules

這樣 case 可以保持語意清楚，而不同平台仍能換掉底層驗證命令。

### 4. Flash sequence discipline

Firmware flash 階段必須保證 **逐步、非組合、前一步完成才可進下一步**。這是硬需求，不可由 plugin 自行合併命令。

對於需要 stateful shell 的平台，plugin 必須使用 interactive session 或等價機制，確保：

1. `cd /tmp`
2. `bcm_flasher $FW_NAME`
3. `bcm_bootstate 1`
4. `reboot`

四個步驟各自單獨送出，且每一步都要等 prompt / terminal evidence 確認完成。

## Architecture

### Component layout

```text
plugins/brcm_fw_upgrade/
  plugin.py
  platform_profiles.yaml
  topology_baselines.yaml
  cases/
    single_dut_upgrade.yaml
    dut_sta_upgrade.yaml
  tests/
    test_brcm_fw_upgrade_schema.py
    test_brcm_fw_upgrade_runtime.py
    test_brcm_fw_upgrade_cli.py
  strategies/
    login.py
    transfer.py
    flash.py
    verify.py
    evidence.py
```

### Responsibilities

#### `plugin.py`

- discover/load cases
- resolve profile + topology baseline + runtime variables
- build per-case execution plan
- enforce phase ordering
- collect structured evidence
- evaluate success gates

`plugin.py` 不直接寫死：

- specific serial commands
- specific verifier regexes
- specific login steps
- specific transfer methods

#### `strategies/login.py`

提供 login strategy：

- `none`
- `serialwrap_profile_login`
- future extension hooks for BDK pre-login sequences

#### `strategies/transfer.py`

提供 transfer strategy：

- host → DUT
- DUT → STA
- direct network copy
- serial-assisted fallback

strategy 的選擇依 capability flags 決定，而不是 case Python code 中的硬編碼判斷。

#### `strategies/flash.py`

負責真正的 flash step engine，保證：

- stateful shell
- command-by-command execution
- completion evidence before next command
- no command chaining in flash stage

#### `strategies/verify.py`

負責：

- MD5 verification
- `/proc/version` build time extraction
- `bcm_bootstate` parsing
- image tag extraction
- ready probe parsing

#### `strategies/evidence.py`

負責：

- serialwrap log capture / slicing
- command stdout/stderr capture
- parsed facts normalization
- report-facing evidence formatting

## Configuration Model

### Layer 1: testbed config

`configs/testbed.yaml` 只放 lab-specific settings：

- selector / alias / session id
- login profile reference
- host / user / password
- artifact root variables
- optional default platform profile

不把升級流程、verifier commands、拓樸依賴寫進 testbed。

### Layer 2: platform profiles

`platform_profiles.yaml` 放平台能力與命令模板。

Example shape:

```yaml
version: "2026-04-21"
profiles:
  bgw720_prpl:
    family: brcm
    board: BGW720-300
    os_flavor: prpl
    login_strategy: none
    capabilities:
      has_scp: true
      has_md5sum: true
      has_bcm_bootstate: true
    commands:
      proc_version: "cat /proc/version"
      image_state: "bcm_bootstate"
      md5: "md5sum {{path}}"
      flash: "bcm_flasher {{fw_name}}"
      reboot: "reboot"
    success_parsers:
      proc_version_build_time: "Linux version .* (?P<build_time>[A-Z][a-z]{2} .+ CST 20[0-9]{2})"
      image_tag: "\\$imageversion: (?P<image_tag>[^$]+) \\$"
    log_markers:
      flash_complete: "Image flash complete"
      delayed_commit: "Delayed commit completed"

  bgw720_bdk:
    family: brcm
    board: BGW720-300
    os_flavor: pure_bdk
    login_strategy: serialwrap_profile_login
    capabilities:
      has_scp: false
      has_md5sum: false
      has_bcm_bootstate: true
```

### Layer 3: topology baselines

`topology_baselines.yaml` 放共用拓樸與 phase 依賴。

Example shape:

```yaml
version: "2026-04-21"
topologies:
  single_dut:
    devices:
      DUT:
        required: true
    phases:
      - precheck
      - transfer_dut
      - flash_dut
      - verify_dut

  dut_plus_sta:
    devices:
      DUT:
        required: true
      STA:
        required: true
    phases:
      - precheck
      - transfer_dut
      - transfer_sta
      - flash_sta
      - verify_sta
      - flash_dut
      - verify_dut
```

### Layer 4: case YAML

case YAML 描述單次升級任務的 intent，而不是 transport 細節。

Example shape:

```yaml
id: brcm-fw-upgrade-dut-sta-forward
name: BGW720 DUT+STA firmware upgrade

platform_profile: bgw720_prpl
topology_ref: dut_plus_sta

artifacts:
  forward_image: "{{FW_FORWARD_PATH}}"
  rollback_image: "{{FW_ROLLBACK_PATH}}"
  active_image_role: forward_image

runtime_inputs:
  fw_name: "{{FW_NAME}}"
  expected_image_tag: "{{EXPECTED_IMAGE_TAG}}"
  expected_build_time: "{{EXPECTED_BUILD_TIME}}"

transfer_policy:
  require_md5_match: true
  prefer_network_copy: true

success_gates:
  - id: build_time_matches
    verifier: proc_version_build_time
    operator: equals
    expected: "{{EXPECTED_BUILD_TIME}}"
  - id: image_tag_matches
    verifier: image_tag
    operator: equals
    expected: "{{EXPECTED_IMAGE_TAG}}"
  - id: boot_target_new
    verifier: booted_partition
    operator: one_of
    expected:
      - First
      - Second

evidence:
  capture:
    - dut_serial
    - sta_serial
    - command_output
  required_for_pass:
    - flash_complete
    - build_time_matches
    - image_tag_matches
```

## CLI and Headless Parameters

Headless 參數是第一版正式需求，不可只依賴手動改 YAML。

### CLI design

沿用現有 plugin helper group pattern，新增：

```bash
testpilot brcm-fw-upgrade run \
  --case dut-sta-forward \
  --forward-image /path/to/0410.pkgtb \
  --rollback-image /path/to/0403.pkgtb \
  --fw-name bcmBGW720-300_squashfs_full_update.pkgtb \
  --expected-image-tag 631BGW720-3001101323 \
  --expected-build-time "Mon Apr 20 13:02:57 CST 2026" \
  --platform-profile bgw720_prpl \
  --topology dut_plus_sta \
  --set DUT_IP=192.168.1.1
```

### Parameter behavior

headless flags 覆寫順序：

1. CLI flags
2. testbed variables
3. case defaults
4. profile defaults

這讓同一個 case 能用不同 image pair 或 lab topology headless 跑起來，而不需要改 repository YAML。

## Execution Pipeline

### Precheck

1. resolve platform profile
2. resolve topology baseline
3. resolve runtime inputs
4. verify local artifact existence
5. verify local artifact MD5
6. verify DUT/STA transport readiness
7. verify remote artifact presence or transfer plan

### Transfer

Transfer strategy 由 capability 選擇：

1. network copy if available
2. intra-topology relay (e.g. DUT → STA)
3. serial-assisted fallback if necessary

### Flash

每個 flash phase 必須嚴格遵守：

1. open/attach stateful shell
2. send `cd /tmp`
3. confirm prompt/location
4. send `bcm_flasher $FW_NAME`
5. wait for completion marker and prompt
6. send `bcm_bootstate 1`
7. wait for completion marker and prompt
8. send `reboot`
9. wait for transport recovery

### Verify

post-boot verification 至少包含：

1. ready probe
2. `/proc/version`
3. image tag / bootstate
4. optional artifact existence / md5 if platform supports it

## Evidence and Reporting

Evidence 是一級輸出，不是 debug 附件。

### Required evidence types

- DUT serialwrap log excerpt
- STA serialwrap log excerpt
- command stdout/stderr
- parsed facts:
  - image tag
  - build time
  - boot partition
  - md5

### Evidence capture points

- precheck
- transfer
- flash
- bootstate set
- reboot
- post-boot verify

### Log slicing model

profile 定義 marker，例如：

- `Image flash complete`
- `Delayed commit completed`
- boot banner
- `/proc/version`
- `bcm_bootstate` output

plugin 依 marker 從 serialwrap evidence 抽出 DUT/STA log 片段，並把它們綁到 success gate。

## Error Handling

1. flash phase 不做 blind retry
2. 任何 command 若未確認完成，不可送下一步
3. 如果 transport recovery 失敗，case 直接 fail，並保留 evidence
4. 如果 verifier command 缺失，交由 profile fallback；若無 fallback，case fail with explicit reason
5. BDK login 若未完成，不允許進入 transfer / flash 階段

## Acceptance Strategy

第一版 live acceptance 用兩組 image 做交互驗證：

1. `0410-VERIFY` → `0403-PATCH`
2. `0403-PATCH` → `0410-VERIFY`

兩種拓樸都要驗：

1. single DUT
2. DUT + STA（先 STA，成功後再 DUT）

## Testing Strategy

### Unit tests

- profile parsing
- case loading
- variable resolution precedence
- verifier parser extraction
- evidence slicing

### Runtime tests

- phase ordering
- single-step flash discipline
- dependency enforcement:
  - `verify_sta` must pass before `flash_dut`
- fallback selection based on capabilities

### Live acceptance

以目前已手動驗證成功的 BGW720 flow 當 acceptance reference。

## Implementation Notes

1. implementation 階段需開新 branch。
2. 新 plugin 從 `plugins/_template/` 起始，但只保留最小骨架，實作放在新目錄結構。
3. 若需要新增 schema 驗證，應擴充 `src/testpilot/schema/case_schema.py`，避免 plugin 私下繞過全域 case validation。
4. 若需要 headless CLI flags，優先沿用現有 `click` 命令風格，並用 plugin helper group 方式暴露。

## Final Recommendation

採用 **BRCM family plugin + platform profiles + topology baselines + headless runtime inputs + evidence-first verification**。

這個方案最符合當前需求邊界：

- 不把 BGW720 寫死在 Python 中
- 能吸收 `prpl` / `pure_bdk` 差異
- 能把 flash flow、success gates、serialwrap log evidence 一起 YAML 化
- 能用目前兩個 image 做可靠的 forward / rollback acceptance
