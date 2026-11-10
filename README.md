# Patient Monitoring Dashboard v2

## Included
- `app.py`: Flask API and COM10 serial reader.
- `templates/index.html`: revised dashboard, no risk percentages or dummy prediction scores.
- Patient 2 and Patient 3 display unavailable.
- Patient 1 status distinguishes missing ECG data from received sensor data.
- Firebase is clearly labelled **Not configured** until real upload code is added.

## Run
```powershell
python -m pip install -r requirements.txt
python app.py
```
Open http://127.0.0.1:5000.

Make sure COM10 is correct, baud rate is 115200, and close Arduino Serial Monitor while Flask owns the port.

## Firebase note
This starter project does NOT write to Firebase. To add real cloud storage, configure Firebase credentials securely (do not put service-account private keys in HTML or commit them), choose Realtime Database or Firestore, add server-side Firebase Admin SDK integration, and update the UI based on actual write success/failure. Never set a “synced” status based only on a configuration flag.

## Patient status note
The dashboard reports whether ECG and temperature readings have arrived. It does not determine clinical health. The presence of a raw ECG sample and temperature value is not enough to classify a patient as healthy.
