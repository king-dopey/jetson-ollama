# ASR Solver Report

Generated: 2026-06-28T14:40:24.591007Z

## Environment Summary

- **Target Python**: 3.12
- **Target Platform**: linux_aarch64
- **CUDA Families**: cu132, cu130, cu128

## Discovery Summary

- **Packages Discovered**: 5
  - ctranslate2: 60 versions
  - faster-whisper: 21 versions
  - torch (cu132): 2 versions
  - torch (cu130): 6 versions
  - torch (cu128): 6 versions
  - torchaudio (cu132): 1 versions
  - torchaudio (cu130): 6 versions
  - torchaudio (cu128): 8 versions
  - whisperx: 44 versions

## Latest Versions Discovered

- **ctranslate2**: 4.8.0
- **faster-whisper**: 1.2.1
- **whisperx**: 3.8.6

### PyTorch Latest Versions by CUDA Family

- **cu132**:
  - torch: 2.12.1+cu132
  - torchaudio: 2.2.0
- **cu130**:
  - torch: 2.12.1+cu130
  - torchaudio: 2.11.0+cu130
- **cu128**:
  - torch: 2.11.0+cu128
  - torchaudio: 2.11.0+cu128

## Candidate Ranking Table

| Rank | Score | CUDA Family | ctranslate2 | faster-whisper | torch | torchaudio | whisperx | Latest | Wheels | Unknown Deps |
|------|-------|-------------|-------------|----------------|-------|------------|----------|--------|--------|--------------|
| 1 | 204998 | cu130 | 4.8.0 | 1.2.1 | 2.11.0+cu130 | 2.11.0+cu130 | 3.8.7rc1 | No | Partial | 0 |
| 2 | 204997 | cu130 | 4.7.2 | 1.2.1 | 2.11.0+cu130 | 2.11.0+cu130 | 3.8.7rc1 | No | Partial | 0 |
| 3 | 204997 | cu130 | 4.8.0 | 1.2.0 | 2.11.0+cu130 | 2.11.0+cu130 | 3.8.7rc1 | No | Partial | 0 |

## Probe Results Table

| Rank | Core Probe | Full Probe | Main Failure | Log Path |
|------|------------|------------|--------------|----------|
| 1 | N/A | N/A | N/A | N/A |
| 2 | N/A | N/A | N/A | N/A |
| 3 | N/A | N/A | N/A | N/A |

## Selected Winner

- **CUDA Family**: cu130
- **ctranslate2**: 4.8.0
- **faster-whisper**: 1.2.1
- **torch**: 2.11.0+cu130
- **torchaudio**: 2.11.0+cu130
- **whisperx**: 3.8.7rc1

- **Selected Rank**: 1
- **Selected Score**: 204998
- **Stack Mode**: full_stack

**Selection Reason**: Selected full_stack stack

## Rejected Newer Candidates and Reasons

No candidates were rejected (only one candidate was evaluated).

## Tech Debt

See `tech-debt.md` for detailed tech debt information.

## Recommended Next Implementation Step

1. Review the selected stack in `selected-stack.env`
2. Update your ASR service Dockerfile to use these versions
3. Run integration tests with the selected stack
4. Monitor for newer versions and update tech debt as needed