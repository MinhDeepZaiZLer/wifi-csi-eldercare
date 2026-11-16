# csi_labeler

GUI collector that reads `CSI_DATA` lines from the RX board, records one CSV per
trial, and appends metadata to `ai/data/index.csv`. This is the dataset source
for `ai/notebooks/train_esp32s3_6class.ipynb`.

## Install and run

```powershell
cd tools\csi_labeler
.\run.ps1
```

`run.ps1` uses `CSI_LABELER_PYTHON` if set, otherwise `.venv`, and creates the
venv on first use. Manual alternative:

```powershell
py -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python csi_labeler.py --port COM11
```

Defaults: receiver `COM11`, 921600 baud, output `ai/data`.

## Operation

1. Connect the RX board (`COM11`) and confirm `Gói/s` is around 70.
2. Fill subject, room, device, repetition; select a label (keys `1..6`).
3. `Space` starts/stops a trial. Changing the label while recording splits a new
   trial automatically.
4. Keep each trial 30–60 s, at least 5 repetitions per label.

| Key | Label |
| --- | --- |
| 1 | `empty` |
| 2 | `walk` |
| 3 | `sit` |
| 4 | `stand` |
| 5 | `lie` |
| 6 | `fall` |

Only simulate falls on a soft mat with an assistant present.

## Output

```
ai/data/
  index.csv
  raw/<subject>/<room>/<label>/<trial_id>.csv
  raw/<subject>/<room>/<label>/<trial_id>.json
```

`index.csv` columns: `trial_id, csv_path, subject, room, label, rep, device,
start_iso, end_iso, duration_s, packets, avg_pps, rssi_mean, csi_lens, fmt,
notes`. Each CSV has 33 columns; `csi_json` is the raw int8 array
(`[Imag1, Real1, ...]`).

`ai/data/*` is gitignored; back it up outside the repo before reinstalling or
cleaning.

See `docs/data/collection-protocol.md` for the full protocol and quality gates.
