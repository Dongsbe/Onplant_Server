from __future__ import annotations

import argparse
import json
import random
import time
from urllib import request


def build_payload(source: str) -> dict[str, float | str]:
    return {
        "lux": round(random.uniform(120.0, 980.0), 1),
        "temperature": round(random.uniform(20.0, 31.5), 1),
        "humidity": round(random.uniform(38.0, 76.0), 1),
        "soil_moisture": round(random.uniform(22.0, 84.0), 1),
        "source": source,
    }


def post_json(url: str, payload: dict[str, float | str]) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Send dummy sensor readings to FastAPI.")
    parser.add_argument("--url", default="http://127.0.0.1:8000/api/sensors")
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--count", type=int, default=0, help="0 means run forever")
    parser.add_argument("--source", default="dummy-client")
    args = parser.parse_args()

    sent = 0
    while args.count == 0 or sent < args.count:
        payload = build_payload(args.source)
        stored = post_json(args.url, payload)
        sent += 1
        print(f"sent id={stored['id']} lux={stored.get('lux')} source={stored.get('source')}")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
