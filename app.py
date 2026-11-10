import os
import re
import threading
import time
from datetime import datetime
from flask import Flask, jsonify, render_template

try:
    import serial
except ImportError:
    serial = None

app = Flask(__name__)

SERIAL_PORT = os.getenv("SERIAL_PORT", "COM10")
BAUD_RATE = int(os.getenv("BAUD_RATE", "115200"))
SERIAL_TIMEOUT = float(os.getenv("SERIAL_TIMEOUT", "1"))

# Firebase is shown as NOT CONFIGURED until real credentials and upload logic exist.
# Set FIREBASE_CONFIGURED=true only after implementing and testing actual writes.
FIREBASE_CONFIGURED = os.getenv("FIREBASE_CONFIGURED", "false").lower() == "true"

lock = threading.Lock()
state = {
    "connected": False,
    "port": SERIAL_PORT,
    "baud_rate": BAUD_RATE,
    "last_update": None,
    "last_line": "",
    "tx1": {},
    "tx2": {},
    "messages": [],
    "serial_error": "Waiting for serial reader to start",
    "active_block": None,
}

def extract(pattern, line, cast=float):
    match = re.search(pattern, line, re.IGNORECASE)
    if not match:
        return None
    try:
        return cast(match.group(1))
    except (ValueError, TypeError):
        return None

def parse_line(raw_line):
    line = raw_line.strip()
    if not line:
        return

    with lock:
        state["last_line"] = line
        state["last_update"] = datetime.now().astimezone().isoformat(timespec="seconds")
        state["messages"].append(line)
        state["messages"] = state["messages"][-15:]

        if "RECEIVED SENSOR TELEMETRY TX-1" in line:
            state["active_block"] = "tx1"
        elif "RECEIVED SENSOR TELEMETRY TX-2" in line:
            state["active_block"] = "tx2"

        block = state["active_block"]
        if block == "tx1":
            patterns = [
                (r"Temperature\s*:\s*(-?\d+(?:\.\d+)?)", "temperature_c"),
                (r"Humidity\s*:\s*(-?\d+(?:\.\d+)?)", "humidity_percent"),
                (r"Vibration\s*:\s*(-?\d+(?:\.\d+)?)", "vibration"),
                (r"Pressure\s*:\s*(-?\d+(?:\.\d+)?)", "pressure_hpa"),
                (r"BMP Temp\s*:\s*(-?\d+(?:\.\d+)?)", "bmp_temperature_c"),
            ]
            for pattern, key in patterns:
                value = extract(pattern, line)
                if value is not None:
                    state["tx1"][key] = value
                    state["tx1"]["available"] = True

        elif block == "tx2":
            vectors = [
                (r"ACCEL\s*\(g\)\s*X:\s*(-?\d+(?:\.\d+)?)\s*\|\s*Y:\s*(-?\d+(?:\.\d+)?)\s*\|\s*Z:\s*(-?\d+(?:\.\d+)?)",
                 ("accel_x_g", "accel_y_g", "accel_z_g")),
                (r"GYRO\s*\(°/s\)\s*X:\s*(-?\d+(?:\.\d+)?)\s*\|\s*Y:\s*(-?\d+(?:\.\d+)?)\s*\|\s*Z:\s*(-?\d+(?:\.\d+)?)",
                 ("gyro_x_dps", "gyro_y_dps", "gyro_z_dps")),
            ]
            for pattern, keys in vectors:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    for i, key in enumerate(keys, 1):
                        state["tx2"][key] = float(match.group(i))
                    state["tx2"]["available"] = True

            for pattern, key in [
                (r"ECG Value\s*:\s*(-?\d+(?:\.\d+)?)", "ecg_raw"),
                (r"Load Cell\s*:\s*(-?\d+(?:\.\d+)?)", "load_cell_g"),
                (r"Water Level\s*:\s*(-?\d+(?:\.\d+)?)", "water_level"),
                (r"DS18B20\s*:\s*(-?\d+(?:\.\d+)?)", "ds18b20_temperature_c"),
            ]:
                value = extract(pattern, line)
                if value is not None:
                    state["tx2"][key] = value
                    state["tx2"]["available"] = True

            if re.search(r"ECG Value\s*:", line, re.IGNORECASE):
                state["tx2"]["ecg_signal"] = "SIGNAL" if "(SIGNAL)" in line.upper() else "NO SIGNAL"

def serial_reader():
    if serial is None:
        with lock:
            state["serial_error"] = "pyserial missing. Run: python -m pip install pyserial"
        return
    while True:
        try:
            with serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=SERIAL_TIMEOUT) as ser:
                with lock:
                    state["connected"] = True
                    state["serial_error"] = ""
                time.sleep(2)
                while True:
                    raw = ser.readline()
                    if raw:
                        parse_line(raw.decode("utf-8", errors="replace"))
        except Exception as exc:
            with lock:
                state["connected"] = False
                state["serial_error"] = f"{type(exc).__name__}: {exc}"
            time.sleep(3)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/data")
def api_data():
    with lock:
        tx1 = dict(state["tx1"])
        tx2 = dict(state["tx2"])
        payload = {
            "connected": state["connected"],
            "port": state["port"],
            "baud_rate": state["baud_rate"],
            "last_update": state["last_update"],
            "tx1": tx1,
            "tx2": tx2,
            "messages": list(state["messages"]),
            "serial_error": state["serial_error"],
            "firebase": {
                "configured": FIREBASE_CONFIGURED,
                "status": "Configured — verify writes" if FIREBASE_CONFIGURED else "Not configured",
                "note": "This starter does not upload telemetry to Firebase yet."
            },
            "patient2": {"available": False},
            "patient3": {"available": False},
        }

    # Raw ECG data is only treated as present if an ECG value has been received.
    ecg_present = tx2.get("ecg_raw") is not None
    temp_present = tx2.get("ds18b20_temperature_c") is not None or tx1.get("temperature_c") is not None
    if not ecg_present:
        patient_status = "Patient data not collected"
        status_detail = "ECG data has not been received yet."
    elif not temp_present:
        patient_status = "Partial data collected"
        status_detail = "ECG data is present; temperature data is not available yet."
    else:
        patient_status = "Monitoring active"
        status_detail = "ECG signal and temperature readings are being received."
    payload["patient1_status"] = patient_status
    payload["patient1_status_detail"] = "ECG signal and temperature readings are being received."
    payload["ecg_present"] = ecg_present
    payload["temperature_present"] = temp_present
    return jsonify(payload)

if __name__ == "__main__":
    threading.Thread(target=serial_reader, daemon=True).start()
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
