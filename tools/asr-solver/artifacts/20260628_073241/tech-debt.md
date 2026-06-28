# ASR Dependency Tech Debt

Generated: 2026-06-28T14:40:25.134440Z

## Debt Entries

### 1. whisperx

- **Chosen Version**: 3.8.7rc1
- **Latest Version**: 3.8.6
- **Reason**: Selected 3.8.7rc1 instead of latest 3.8.6 due to compatibility constraints
- **Risk Level**: medium
- **Removal Trigger**: Update when 3.8.6 is verified compatible
- **Suggested Follow-up**: Test with 3.8.6 and update if compatible

### 2. cuda

- **Chosen Version**: cu130
- **Latest Version**: cu132
- **Reason**: Selected cu130 instead of cu132 due to compatibility constraints
- **Risk Level**: high
- **Removal Trigger**: Update when cu132 is verified compatible
- **Suggested Follow-up**: Test with cu132 and update if compatible

## Summary

Total debt entries: 2