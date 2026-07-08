import requests

# RELAY_URL = "http://127.0.0.1:8899"  # later: https://cryolauncher.com
RELAY_URL = "http://cryostack.eas.gatech.edu"


def create_session():
    r = requests.post(f"{RELAY_URL}/connector/session")
    return r.json()


def check_status(session_id):
    r = requests.get(f"{RELAY_URL}/connector/status/{session_id}")
    return r.json()


def send_command(session_id, command_type, payload):
    r = requests.post(
        f"{RELAY_URL}/connector/command/{session_id}",
        json={
            "command_type": command_type,
            "payload": payload,
        },
        timeout=120,
    )
    return r.json()