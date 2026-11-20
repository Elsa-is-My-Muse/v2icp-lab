import json
import math
import re
from dataclasses import dataclass


MAX_PAYLOAD = 512
USER_AGENT = "V2ICP-Client/2.0.0"
CONTENT_TYPE = "application/json; charset=US-ASCII"


class ProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class Signal:
    minimum: int
    maximum: int
    resolution: int = 1
    sna: int = -1

    def validate(self, name, value):
        if type(value) is not int:
            raise ProtocolError(f"{name} must be an integer, not {type(value).__name__}")
        if value != self.sna and not self.minimum <= value <= self.maximum:
            raise ProtocolError(f"{name} out of raw range: {value}")
        return value

    def physical(self, name, value):
        self.validate(name, value)
        return None if value == self.sna else value * self.resolution


VEHICLE_SIGNALS = {
    "odo": Signal(0, 21055406),
    "bat_reqtime": Signal(0, 250),
    "bat_eamount": Signal(0, 1000),
    "prec_eamount": Signal(0, 1000),
    "prec_reqtime": Signal(0, 250),
    "chrg_stat": Signal(0, 4),
    "h2_stat": Signal(0, 1),
    "bat_stat": Signal(0, 1),
}

BACKEND_SIGNALS = {
    "driveoff": Signal(0, 288, resolution=5),
    "prec_dsrd": Signal(0, 1),
    "prec_hvac": Signal(0, 3),
    "ambienttemp": Signal(-50, 70, sna=-51),
    "target_dist": Signal(0, 1000),
    "target_soc": Signal(0, 100),
}


def encode_payload(message):
    try:
        payload = json.dumps(message, ensure_ascii=True, separators=(",", ":"),
                             allow_nan=False).encode("ascii")
    except (ValueError, TypeError) as exc:
        raise ProtocolError(str(exc)) from exc
    if len(payload) > MAX_PAYLOAD:
        raise ProtocolError(f"payload exceeds {MAX_PAYLOAD} bytes")
    return payload


def _unique_object(pairs):
    result = {}
    for name, value in pairs:
        key = name.lower()
        if key in result:
            raise ProtocolError(f"duplicate JSON key: {name}")
        result[key] = value
    return result


def _reject_constant(value):
    raise ProtocolError(f"invalid JSON number: {value}")


def decode_payload(payload):
    if len(payload) > MAX_PAYLOAD:
        raise ProtocolError(f"payload exceeds {MAX_PAYLOAD} bytes")
    try:
        message = json.loads(payload.decode("ascii"), object_pairs_hook=_unique_object,
                             parse_constant=_reject_constant)
    except (ValueError, UnicodeError) as exc:
        raise ProtocolError(f"invalid JSON: {exc}") from exc
    if not isinstance(message, dict):
        raise ProtocolError("payload must be one JSON object")
    return message


def validate_identity(message):
    sequence = message.get("seq")
    if type(sequence) is not int or not 0 <= sequence <= 255:
        raise ProtocolError("seq must be an integer in 0..255")
    vin = message.get("vin")
    if not isinstance(vin, str) or re.fullmatch(r"[A-Za-z0-9]{17}", vin) is None:
        raise ProtocolError("vin must contain exactly 17 ASCII letters/digits")


def validate_signals(message, signals):
    for name, signal in signals.items():
        if name in message:
            signal.validate(name, message[name])


def validate_request(message):
    validate_identity(message)
    evccid = message.get("evccid")
    if not isinstance(evccid, str) or re.fullmatch(r"[A-Fa-f0-9]{12}", evccid) is None:
        raise ProtocolError("evccid must contain exactly 12 hexadecimal characters")
    for name in ("h2_stat", "bat_stat"):
        if name not in message:
            raise ProtocolError(f"missing mandatory signal: {name}")
    if message["seq"] == 0:
        missing = set(VEHICLE_SIGNALS) - message.keys()
        if missing:
            raise ProtocolError(f"first request must contain all signals, use SNA: {sorted(missing)}")
    validate_signals(message, VEHICLE_SIGNALS)


def validate_response(message, request):
    validate_identity(message)
    if message["seq"] != request["seq"] or message["vin"] != request["vin"]:
        raise ProtocolError("response seq/vin does not match the request")
    validate_signals(message, BACKEND_SIGNALS)
    if message["seq"] == 0 and set(BACKEND_SIGNALS) - message.keys():
        raise ProtocolError("seq=0 response must contain all backend signals")


class VehicleSnapshot:
    def __init__(self, vin, evccid, values=None):
        self.vin = vin
        self.evccid = evccid
        self.values = {name: signal.sna for name, signal in VEHICLE_SIGNALS.items()}
        self.previous = None
        self.update(values or {})

    def update(self, values):
        for name, value in values.items():
            if name not in VEHICLE_SIGNALS:
                raise ProtocolError(f"not a vehicle-to-backend signal: {name}")
            VEHICLE_SIGNALS[name].validate(name, value)
        self.values.update(values)

    def request(self, sequence):
        message = {"seq": sequence, "vin": self.vin, "evccid": self.evccid}
        for name, value in self.values.items():
            if (sequence == 0 or self.previous is None or name in ("h2_stat", "bat_stat")
                    or self.previous.get(name) != value):
                message[name] = value
        validate_request(message)
        return message

    def record_sent(self, message):
        if self.previous is None:
            self.previous = {}
        self.previous.update({name: message[name] for name in VEHICLE_SIGNALS if name in message})

    def new_connection(self):
        self.previous = None


def backend_values(plan, departure_monotonic, now):
    values = {name: signal.sna for name, signal in BACKEND_SIGNALS.items()}
    values.update({name: plan[name] for name in BACKEND_SIGNALS if name in plan})
    if departure_monotonic is not None:
        values["driveoff"] = max(0, math.ceil((departure_monotonic - now) / 300))
    validate_signals(values, BACKEND_SIGNALS)
    return values
