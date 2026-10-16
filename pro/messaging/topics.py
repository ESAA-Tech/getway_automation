"""
Standard MQTT Topic Architecture for SCMP Light Pole Platform (No Ring).
Directly aligns with scmp-backend/packages/common/src/topics/index.ts.

Pattern: scmp/v1/{siteId}/{poleCode}/{deviceType}/{deviceId}/{direction}[/{action}]
"""

from typing import Optional, Dict, Any, Literal

MQTT_SHARED_GROUP = "scmp_ingestion"
MQTT_TOPIC_PREFIX = "scmp/v1"

DeviceType = Literal[
    "lamp",
    "screen",
    "rgb",
    "env",
    "speaker",
    "camera",
    "sos",
    "gateway"
]

TopicDirection = Literal[
    "telemetry",
    "status",
    "cmd",
    "ack",
    "event"
]

VALID_DEVICE_TYPES = {
    "lamp",
    "screen",
    "rgb",
    "env",
    "speaker",
    "camera",
    "sos",
    "gateway"
}

VALID_DIRECTIONS = {
    "telemetry",
    "status",
    "cmd",
    "ack",
    "event"
}

MQTT_SUBSCRIPTIONS = {
    "SHARED_TELEMETRY": f"$share/{MQTT_SHARED_GROUP}/{MQTT_TOPIC_PREFIX}/+/+/+/+/telemetry",
    "SHARED_STATUS": f"$share/{MQTT_SHARED_GROUP}/{MQTT_TOPIC_PREFIX}/+/+/+/+/status",
    "SHARED_EVENT": f"$share/{MQTT_SHARED_GROUP}/{MQTT_TOPIC_PREFIX}/+/+/+/+/event/+",
    "SHARED_ACK": f"$share/{MQTT_SHARED_GROUP}/{MQTT_TOPIC_PREFIX}/+/+/+/+/ack/+",
}


def build_device_topic(
    site_id: str,
    pole_code: str,
    device_type: str,
    device_id: str,
    direction: str,
    action: Optional[str] = None
) -> str:
    """
    Constructs an SCMP standardized MQTT topic.
    scmp/v1/{siteId}/{poleCode}/{deviceType}/{deviceId}/{direction}[/{action}]
    """
    base = f"{MQTT_TOPIC_PREFIX}/{site_id}/{pole_code}/{device_type}/{device_id}/{direction}"
    return f"{base}/{action}" if action else base


def parse_device_topic(topic: str) -> Optional[Dict[str, Any]]:
    """
    Parses an SCMP standardized MQTT topic into metadata components.
    Expected: scmp/v1/{siteId}/{poleCode}/{deviceType}/{deviceId}/{direction}[/{action}]
    """
    if not topic or not isinstance(topic, str):
        return None

    segments = topic.split("/")
    if len(segments) < 7 or segments[0] != "scmp" or segments[1] != "v1":
        return None

    site_id = segments[2]
    pole_code = segments[3]
    device_type = segments[4]
    device_id = segments[5]
    direction = segments[6]
    action = "/".join(segments[7:]) if len(segments) > 7 else None

    return {
        "site_id": site_id,
        "pole_code": pole_code,
        "device_type": device_type,
        "device_id": device_id,
        "direction": direction,
        "action": action,
        "raw_topic": topic
    }
