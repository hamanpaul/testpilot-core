---
type: feat
scope: plugin-sdk
issue: 268
---
Add SDK API 1.5 teardown results so Core can surface failed or unverified cleanup as a terminal environment failure before retry or later case execution. Legacy plugins returning `None` keep the existing successful-cleanup behavior.
