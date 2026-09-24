# CycleSafe Data Dictionary

This document details every field collected in the system, its specific purpose, and its related functionality.

| Field | Description | Purpose | Features Using This |
| --- | --- | --- | --- |
| `cycle_length_days` | The length of a menstrual cycle in days | Core tracking of period patterns and predicting future cycles. | Forecasting, Rules Engine (R3, R6) |
| `pain_score` | A scale (0-3) rating cycle pain | Monitoring severity and frequency of pain. | Rules Engine (R1) |
| `bleeding_heaviness` | A scale (0-3) describing blood flow | Monitoring flow to alert for overly heavy bleeding. | Rules Engine (R2) |
| `bleeding_days` | Number of bleeding days per cycle | Monitoring prolonged periods. | Rules Engine (R2) |
| `spotting_between_periods`| Boolean indicating spotting | Tracking mid-cycle variations. | Symptom Tracking |
| `mood_score` | A scale (0-3) for emotional state | Alerting users to persistent mood drops. | Rules Engine (R5) |
| `sleep_score` | A scale (0-3) for sleep quality | General wellness tracking. | Symptom Tracking |
| `fatigue_score` | A scale (0-3) for fatigue | General wellness tracking. | Symptom Tracking |
| `hot_flash_count` | Count of hot flashes | Tracking perimenopause transition symptoms. | Perimenopause Monitoring |
| `hot_flash_severity` | Scale (0-3) for hot flash intensity | Tracking perimenopause transition severity. | Perimenopause Monitoring |
| `night_sweats` | Boolean indicating night sweats | Tracking perimenopause symptoms. | Perimenopause Monitoring |
| `skipped_period` | Boolean indicating missed period | Detecting missed cycles. | Perimenopause, Rules Engine (R4) |
