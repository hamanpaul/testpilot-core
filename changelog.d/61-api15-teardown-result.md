---
type: feat
scope: plugin-sdk
issue: 61
---
Add SDK API 1.5 teardown results so Core can surface failed or unverified cleanup as a terminal environment failure before retry or later case execution. Accepted transport receipts without completion evidence are promoted to unknown through nested cleanup wrappers. Legacy plugins returning `None` keep the existing successful-cleanup behavior.
