## Context

The plugin-facing run loop already calls `capture_dut_firmware_version()` for report naming when the CLI does not supply `--dut-fw-ver`. The 2026-07-08 plan changes that contract: plugins will return a full manifest dict, the core loop must always capture it even when naming comes from the CLI, and generic HTML/Markdown reporters should surface the manifest as a collapsed Environment / Versions block near the top of the report.

## Goals / Non-Goals

**Goals:**
- Capture the plugin version manifest exactly once at run start and store it in `meta["version_manifest"]`.
- Preserve current naming precedence so `--dut-fw-ver` still wins for the report filename while the manifest is still captured for metadata/reporting.
- Render a collapsed Environment / Versions section in HTML and Markdown only when the manifest exists.
- Keep the core implementation plugin-agnostic; the generic layer should know only about the `version_manifest` metadata key.

**Non-Goals:**
- Defining the manifest field list or DUT command parsing logic; that remains plugin-owned.
- Modifying XLSX report generation, which is wifi_llapi-specific.
- Introducing new plugin hooks or changing case-execution semantics outside the run-start capture path.

## Decisions

1. **Unconditional manifest capture**
   - `run_loop` will call the plugin hook even when the CLI provided `--dut-fw-ver`.
   - The naming helper will continue to prefer the CLI argument, but the captured manifest is always stored in metadata for downstream reporters.

2. **String naming derives from manifest `git` field**
   - When no CLI override exists, the core loop uses `manifest.get("git", "")` as the report firmware string.
   - This keeps backward-compatible naming semantics while allowing the hook return type to evolve from `str` to `dict`.

3. **Generic reporters render a no-op-when-absent details block**
   - HTML and Markdown reporters will add the Environment / Versions section immediately after the header and before KPI/summary sections.
   - If `version_manifest` is missing or empty, reporters leave existing output unchanged.

4. **Plugin-neutral metadata contract**
   - The core layer will use only `meta["version_manifest"]` and generic labels such as "Environment / Versions".
   - No `wifi_llapi` string or plugin-specific field assumptions beyond iterating the provided mapping are introduced in the shared reporters.

## Risks / Trade-offs

- **Hook return type drift across repos** → verify wifi_llapi against the core worktree editable install and land both PRs together.
- **Generic reporter clutter** → keep the section collapsed by default and skip it entirely when metadata is absent.
- **Malformed plugin metadata** → the core loop/reporter path should guard shape checks and degrade to a no-op instead of crashing report generation.
