# Changelog

## [9.0.6] - 2026-01-07

### Added
- **SSL Optimization**: Disabled `OP_NO_TICKET` and `OP_NO_COMPRESSION` in `protocol_8888.py` to reduce memory usage on low-resource devices (e.g., older Samsung ACs).
- **Transient Error Handling**:Implemented a "strike system" in `samsung_2878.py`. Connection errors are now tracked, and a full reset is only triggered after 3 consecutive failures ("strikes"), preventing unnecessary restarts due to temporary network glitches.
- **Logging**: Added verification logs to confirm which SSL optimizations are successfully applied.

### Fixed
- **Outdoor Temperature**: Corrected the outdoor temperature calculation in `samsung_2878.yaml` by subtracting 55 from the raw device value to get the correct Celsius reading.
