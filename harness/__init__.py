"""The replay harness: a fake camera, a scripted person, and a stopwatch.

No Misty II exists for this project and none ever will (PLAN.md §1), so the
only way to measure how stale a distance reading is, is to build a camera whose
ground truth is known by construction and play a script through the real
perception pipeline.

What it measures, and what it cannot:

```
[真值] ─ 曝光 → 編碼 → RTSP over WiFi ─▶ [進 process] ─ 緩衝/偵測/濾波 ─▶ [讀數]
        └──── 截段 A：需要硬體，量不到 ───┘  └──── 截段 B：這裡量的就是這段 ────┘
```

The harness injects frames exactly where RTSP would deliver them, so segment B
is measured end to end. Segment A is represented by the ``sensor_transport_lag_s``
configuration value, marked UNCALIBRATED, and swept rather than measured.

Its job changed at PLAN.md §12.4. It was built to prove the old pipeline was
broken; the project moved to rewriting rather than patching, so it now measures
the numbers the new pipeline has to hit.
"""
