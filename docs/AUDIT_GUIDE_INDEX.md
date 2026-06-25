# TestPilot Audit Guide — Document Index

**Created**: 2026-03-23  
**Status**: Complete examination and reference guide  
**Primary Document**: `COMPREHENSIVE_AUDIT_GUIDE.md` (35 KB, 953 lines)

---

## Quick Start

**Your main resource**: `/home/paul_chen/prj_pri/testpilot/COMPREHENSIVE_AUDIT_GUIDE.md`

This document contains **everything you need** to:
- Understand the audit framework and current project status
- Write audit entries with proper format and evidence
- Continue calibration work using the single-case methodology
- Ensure compliance with report standards and policies

---

## What You Have

### Primary Deliverable

**File**: `COMPREHENSIVE_AUDIT_GUIDE.md` (35 KB)

**11 Main Parts + 5 Appendices**:
1. Executive Summary — current status (370/415 = 89%)
2. Project Structure — directory layout, 8 key files
3. YAML Case Schema — complete D093 example
4. Calibration Methodology — 7-step loop, 13 critical rules
5. Report Format Standards — mandatory structure
6. Case Discovery & Regression — conventions, 521 tests
7. Agent Configuration — 3-tier model policy
8. Report Metadata — workbook reference
9. Practical Example — detailed D093 audit entry
10. Continuation & Resumption — 6-step checklist
11. Key Metrics & Progress Tracking — status dashboard
Appendices A–E: Glossary, Workbook columns, Verdicts, Blockers, Lab checklist

---

## Key Information at a Glance

### Current Status (2026-03-20)
- **Calibrated**: 370 / 415 (89%)
- **Remaining**: 186 cases
- **Active Blockers**: 3 (D035, D052, D053)
- **Test Suite**: 521 passing
- **Report Size**: 488 KB (170+ case sections)

### Authority & Baseline
- **Workbook**: `0310-BGW720-300_LLAPI_Test_Report.xlsx`
- **Columns**: L (5G) / M (6G) / N (2.4G) = verdict authority
- **DUT**: COM0 (B0 class, BGW720)
- **STA**: COM1 (prplOS B0 class)
- **Baseline**: WPA2-Personal (5G/2.4G) + WPA3-SAE (6G), password `00000000`

### 13 Critical Validation Rules
1. Read-only verification
2. Refresh/trigger actions
3. Side-effect verification
4. Counter validation
5. Workbook non-pass handling
6. DUT/STA identity (not A0/B0)
7. YAML sync scope
8. Default non-open baseline
9. Baseline acceptance criteria
10. Available-tools rule
11. Blocker vs. environmental issues
12. Continuation guard rails
13. Single-case mode only

### Report Format (Mandatory)
- Collapsible markdown sections (`<details>`)
- Per-case summary table (id | row | API | verdict | logs)
- Evidence blocks with exact commands/output
- Log references in `Lxxx-Lyyy` format
- Baseline restore checkpoint

### Single-Case Loop (7 Steps)
1. Offline survey
2. Normalization
3. Precondition & environment
4. Live serialwrap execution
5. Evidence analysis
6. Decision logic (match/mismatch)
7. Repository sync (YAML + tests + docs)

---

## How to Use This Guide

### Scenario 1: Writing Your First Audit Entry

**Steps**:
1. Open `COMPREHENSIVE_AUDIT_GUIDE.md`
2. Go to **Part 8: Practical Example**
3. Read the D093 example (structure, format, evidence)
4. Follow the same structure for your case
5. Reference **Part 4: Report Format Standards** for formatting details
6. Commit with case ID and verdict in message

### Scenario 2: Understanding Validation Rules

**Steps**:
1. Open `COMPREHENSIVE_AUDIT_GUIDE.md`
2. Go to **Part 3: Audit Calibration Methodology**
3. Find section **"Critical Validation Rules"**
4. Read the 13 rules with examples
5. Reference specific rule when writing your audit entry
6. See **Appendix D: Common Blocker Patterns** for similar cases

### Scenario 3: Continuing Calibration Work

**Steps**:
1. Open `COMPREHENSIVE_AUDIT_GUIDE.md`
2. Go to **Part 9: Continuation & Resumption**
3. Follow the 6-step checklist to resume
4. Identify next case from audit report checkpoint
5. Apply **Part 3: Calibration Methodology** 7-step per-case loop
6. Write audit entry, update docs, commit
7. Proceed to next case (do NOT stop)

### Scenario 4: Lab Setup or Troubleshooting

**Steps**:
1. Open `COMPREHENSIVE_AUDIT_GUIDE.md`
2. Go to **Part 3: Lab Environment Configuration**
3. Reference DUT/STA band mapping and BSSID/MAC
4. Check **Appendix E: Lab Environment Setup Checklist**
5. Read CRITICAL lab rule about COM1 br-lan isolation
6. Rebuild mapping from live evidence if needed

### Scenario 5: Report Format Compliance

**Steps**:
1. Open `COMPREHENSIVE_AUDIT_GUIDE.md`
2. Go to **Part 4: Audit Report Format & Standards**
3. Review "Report Structure" and "Mandatory Evidence"
4. Check current report: `plugins/wifi_llapi/reports/audit-report-260313-185447.md`
5. Match structure exactly (collapsible sections, summary table, evidence blocks)
6. Use `Lxxx-Lyyy` log references where known

---

## Reference Materials Used

### Source Files Examined

| File | Lines | Purpose |
|------|-------|---------|
| `docs/audit-todo.md` | 606 | Calibration authority, rules, todo list |
| `docs/plan.md` | 160 | Master roadmap, phases, gates |
| `AGENTS.md` | 129 | Report policy, agent config, baseline |
| `audit-report-260313-185447.md` | 488KB | Live evidence, 170+ case sections |
| `docs/` | 8 files | Documentation structure |
| `plugins/wifi_llapi/` | 415+ cases | YAML case files, agent config |
| `plugins/<plugin>/testbed.yaml.example` | 30 | Per-plugin testbed template (auto-staged into `configs/testbed.yaml`) |
| `schema/case_schema.py` | 102 | YAML validation rules |
| `D093_ssidadvertisementenabled.yaml` | 234 | Complete case example |

### Key Documentation Structure

```
docs/
├── audit-todo.md              ← Calibration authority & checklist
├── plan.md                    ← Master roadmap & phases
├── spec.md                    ← Architecture & boundaries
├── todos.md                   ← Project-wide todo list
└── copilot-sdk-*.md          ← Third refactor research

plugins/wifi_llapi/
├── cases/                     ← 415 test case YAML files
├── plugin.py                  ← LLAPI plugin implementation
├── agent-config.yaml          ← Agent/model configuration
└── reports/
    ├── audit-report-*.md      ← Live evidence & checkpoints
    ├── templates/             ← Excel templates
    └── agent_trace/           ← Agent session logs

COMPREHENSIVE_AUDIT_GUIDE.md  ← YOUR REFERENCE (THIS FILE'S PEER)
```

---

## Document Navigation

### By Topic

**Project Structure**:
→ Part 1: Project Structure and Key Files
→ Part 11, Section "Key Documents & Quick Reference"

**Understanding Test Cases**:
→ Part 2: YAML Case Schema
→ Part 8: Practical Example (D093)

**Calibration Methodology**:
→ Part 3: Audit Calibration Methodology
→ Part 9: Continuation & Resumption

**Report Writing**:
→ Part 4: Audit Report Format & Standards
→ Part 8: Practical Example
→ Appendix C: Verdict Categories

**Lab Configuration**:
→ Part 3, Section "Lab Environment Configuration"
→ Appendix E: Lab Environment Setup Checklist

**Agent & Policies**:
→ Part 6: Agent Configuration & Policy
→ Part 3, Section "Current DUT/STA Mapping & Lab Rules"

**Progress Tracking**:
→ Part 10: Key Metrics & Progress Tracking
→ Part 11: Key Documents

### By Role

**Audit Writer**:
1. Read Part 8 (Practical Example)
2. Read Part 4 (Report Format)
3. Read Part 3 (Validation Rules)
4. Write audit entry following D093 structure

**Calibration Technician**:
1. Read Part 9 (Continuation)
2. Read Part 3 (7-step loop, 13 rules)
3. Follow single-case methodology
4. Update docs after each case

**Project Manager**:
1. Read Executive Summary
2. Read Part 10 (Metrics & Progress)
3. Review Part 9 (Continuation guard rails)
4. Track status from audit report checkpoints

**New Team Member**:
1. Read Executive Summary
2. Read Part 1 (Project Structure)
3. Read Part 3 (Calibration Methodology)
4. Review Part 11 (Quick Reference)
5. Study Part 8 (Example case)

---

## Common Tasks & Solutions

### "I need to write an audit entry for case D098"

→ Open `COMPREHENSIVE_AUDIT_GUIDE.md` Part 8  
→ Copy structure from D093 example  
→ Replace case-specific details (commands, output, verdicts)  
→ Verify against **Part 4: Report Format Standards**  
→ Reference **Part 3: Validation Rules** for verdict justification

### "I don't understand the 13 rules"

→ Open `COMPREHENSIVE_AUDIT_GUIDE.md` Part 3  
→ Read section **"Critical Validation Rules"**  
→ Cross-reference with **Appendix D: Common Blocker Patterns**  
→ Find similar case in audit report for examples

### "I'm resuming work after a break"

→ Open `COMPREHENSIVE_AUDIT_GUIDE.md` Part 9  
→ Follow 6-step resumption checklist  
→ Read latest checkpoint in `audit-report-260313-185447.md`  
→ Use **Part 3: Calibration Methodology** 7-step loop for next case  
→ Do NOT stop after first commit; continue to next case

### "I need to understand the lab setup"

→ Open `COMPREHENSIVE_AUDIT_GUIDE.md` Part 3  
→ Read **"Lab Environment Configuration"** section  
→ Check **Appendix E: Lab Environment Setup Checklist**  
→ Pay ATTENTION to critical rule about COM1 br-lan isolation  
→ Verify using commands in Part 3

### "The report format isn't clear"

→ Open `COMPREHENSIVE_AUDIT_GUIDE.md` Part 4  
→ Review **"Report Structure (from AGENTS.md Section 7)"**  
→ Look at current report: `audit-report-260313-185447.md`  
→ Follow collapsible section, summary table, evidence block structure  
→ Use **Part 8: Practical Example** as template

### "I need to know current status"

→ Open `COMPREHENSIVE_AUDIT_GUIDE.md` Part 10  
→ Review **"Current Status (2026-03-20)"** metrics table  
→ Read **"Calibration Phases"** for work breakdown  
→ Check **Part 11: Key Metrics** for detailed progress  
→ Reference **Part 3** for next ready cases

---

## Key Phone Numbers (Important Facts)

- **Total Cases**: 415 official test cases
- **Calibrated**: 370 (89%)
- **Remaining**: 186 (26%)
- **Blockers**: 3 active (D035, D052, D053)
- **Test Pass Rate**: 521 / 521 (100%)
- **Audit Report**: 488 KB with 170+ case sections
- **Single-Case Time**: Typical 30–60 minutes per case
- **Workbook Columns**: L (5G) / M (6G) / N (2.4G) = verdict authority
- **DUT/STA Bands**: 3 verified (5G/6G/2.4G)

---

## Final Notes

**The COMPREHENSIVE_AUDIT_GUIDE.md is your complete reference.** It contains:
- All structural information you need
- Complete methodology documentation
- Working examples you can follow
- Policy requirements to comply with
- Lab configuration details
- Continuation procedures

**Use it as your "bible" for**:
- Writing audit entries
- Understanding validation rules
- Continuing calibration work
- Ensuring report compliance
- Troubleshooting lab issues

**All your questions should be answerable from this single document.**

---

**Document Index Created**: 2026-03-23  
**Guide Status**: Complete and ready for use  
**Location**: `/home/paul_chen/prj_pri/testpilot/COMPREHENSIVE_AUDIT_GUIDE.md`

