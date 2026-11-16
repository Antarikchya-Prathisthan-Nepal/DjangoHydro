import json, datetime
now = datetime.datetime.utcnow()
payload = {
    "GST_data": {
        "credentials": {"username": "gst_user", "password": "apn_sajan_123"},
        "station_id": {
            "id": "GST_TEST_001",
            "location": {"lat": 27.6853, "lon": 85.5234},
            "timestamp": {
                "date": now.strftime("%d/%m/%Y"),
                "time": now.strftime("%H:%M:%S"),
                "day": now.strftime("%A"),
            },
            "electrical_params": {"sol_current": 1.35, "load_current": 0.72},
        },
        "status": 1,
        "wifi_strength": -68,
        "station_data": [{
            "ip_address": "192.168.1.42",
            "sensors_data": {"temp": 28.4, "pressure": 1012.5, "humidity": 74.2, "depth": 268.0, "air_quality": 43.0},
        }],
    }
}
with open("/tmp/gst_test.json", "w") as f:
    json.dump(payload, f)
print("Payload written with timestamp:", now.strftime("%H:%M:%S"))
