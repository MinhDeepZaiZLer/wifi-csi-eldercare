# CSI data collection protocol

Goal: a labelled dataset that generalizes across people and rooms, so the
6-class model can be evaluated with a held-out subject/room split.

## Safety

- Simulate falls **only** on a soft mat, with an assistant present.
- No fall trial on stairs, wet floors, or near furniture edges.
- Stop immediately if the subject feels pain or dizziness.

## Hardware setup

| Item | Value |
| --- | --- |
| TX board | `COM7`, sender firmware, channel 11 |
| RX board | `COM11`, node firmware, channel 11 |
| Link distance | 1–3 m, both boards fixed at ~1 m height |
| Orientation | boards facing each other, line of sight for baseline trials |
| Capture | `tools/csi_labeler`, 921600 baud |
| Expected rate | ~70 packets/s (`pps`), `csi_len = 384` |
| RSSI target | -30 to -60 dBm (move boards apart if closer than -25) |

Keep the boards and furniture in the same position for a whole session. Record
the layout in the trial `notes` when it changes.

## Classes

| Label | Definition | Typical duration |
| --- | --- | --- |
| `empty` | no person in the link, room quiet | 30–60 s |
| `walk` | walking across or inside the link, normal speed | 30–60 s |
| `sit` | sitting on a chair inside the link, small movements | 30–60 s |
| `stand` | standing still inside the link | 30–60 s |
| `lie` | lying on the mat calmly, **no fall transition** | 30–60 s |
| `fall` | controlled fall from standing onto the mat | 3–6 s per event |

`lie` and `fall` must be distinct: `lie` starts already on the mat, `fall`
contains the standing-to-ground transition. Do not label the recovery as fall.

## Trial plan

Minimum for a deployable model:

- **3 subjects** (different body sizes), at least 1 not used in training.
- **2 rooms** per subject where possible; hold out one room.
- **5 trials per class** per subject/room, 30–60 s each.
- **15 fall trials minimum** (5 per subject), spread over sessions.
- Aim for **≥ 200 windows** total; 250-packet windows with stride 125 give
  ~2 windows per 3.4 s of a 30 s trial.

Per session, cycle: `empty → walk → sit → stand → lie → fall`, then change
subject/room and repeat. Use `rep` to number repetitions.

## Procedure

1. Power both boards; verify `pps ≈ 70`, `csi_len = 384`, low `motion` in
   `empty`.
2. Start `tools\csi_labeler\run.ps1`, connect `COM11`.
3. Fill subject/room/device, select label, press `Space`.
4. Perform the activity for 30–60 s (fall: one transition, then stop).
5. Press `Space` to stop; the trial is written and `rep` increments.
6. Check `packets` and `avg_pps` in the log; discard trials with `packets < 500`
   or long gaps.
7. Repeat for all classes before moving the boards.

## Quality gates per trial

- `packets ≥ 500` (30 s at ~70 pps gives ~2100).
- `csi_lens = [384]`, `fmt = esp32s3`.
- `avg_pps` between 50 and 90.
- `rssi_mean` between -65 and -25 dBm.
- `empty` trials: `motion` mostly below 0.02.
- No missing `csi_json`, no `None`/empty rows.

## Dataset layout and split

```
ai/data/index.csv
ai/data/raw/<subject>/<room>/<label>/<trial_id>.csv
ai/data/raw/<subject>/<room>/<label>/<trial_id>.json
```

Split **by trial**, never by window: all windows of a trial go to one split.
Use leave-one-subject-out or leave-one-room-out, and report both if possible.
The notebook writes `deployable` and the split name into `model_info.json`.

## Handoff to the model

1. Zip `ai/data` (index.csv + raw/) and upload it as a Kaggle dataset.
2. Run `ai/notebooks/train_esp32s3_6class.ipynb`.
3. Return `esp32s3_csi_model.zip` with `model_data.h`, `model_info.json`,
   `metrics.json`, `classification_report.txt`, confusion matrix, and curves.

Do not commit `ai/data` or model binaries; both are gitignored.
