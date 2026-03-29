#!/usr/bin/env python3
import configparser
import json
import socket
import sys
import requests
import time


OID = "1.3.6.1.4.1.2435.2.3.9.2.11.1.1.0"

FUNCTIONS = [
    ("IMAGE", 1),
    ("OCR", 3),
    ("EMAIL", 2),
    ("FILE", 5),
]


def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Es wird keine echte Verbindung aufgebaut,
        # das dient nur dazu, die passende lokale IP zu ermitteln.
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    finally:
        s.close()


def load_config(path="config.ini"):
    config = configparser.ConfigParser()
    read_files = config.read(path)
    
    printer_ip = config["device"]["printer_ip"].strip()
    raw_names = config["users"]["names"]
    users = [name.strip() for name in raw_names.split(",") if name.strip()]

    return printer_ip, users


def build_payload(user_name, pi_ip):
    request_entries = []

    for func_name, appnum in FUNCTIONS:
        value = (
            f"TYPE=BR;BUTTON=SCAN;USER={user_name};FUNC={func_name};"
            f"HOST={pi_ip}:54925;APPNUM={appnum};DURATION=360;BRID=;"
        )
        request_entries.append({
            "key": OID,
            "string_value": value
        })

    return {"request": request_entries}


def send_registration(printer_ip, payload):
    url = f"https://{printer_ip}/phoenix/mib"

    response = requests.post(
        url,
        auth=requests.auth.HTTPDigestAuth("Public", "0000"),
        headers={"Content-Type": "application/json"},
        json=payload,
        verify=False,
        timeout=15,
    )

    response.raise_for_status()


def main():
    printer_ip, users = load_config()
    pi_ip = get_local_ip()
    
    while True:
        try:
            for user in users:
                payload = build_payload(user, pi_ip)
                send_registration(printer_ip, payload)
        except Exception as e:
            print(f"Error: {e}")
        time.sleep(360)
    

if __name__ == "__main__":
    main()
