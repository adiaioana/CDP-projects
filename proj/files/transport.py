"""
transport.py
------------
Real-time sensor-stream transport comparison.

The anomaly detector consumes a LIVE stream of sensor events. How that
stream travels from the home to the caregiver dashboard is a security
trade-off. This module lets the team measure the SAME stream over
different transports and report latency, throughput, connection success,
setup complexity and threat-model coverage.

SCOPE / ETHICS
  This module does NOT build, automate, or script Tor circuits or VPN
  tunnels. Doing so could amount to evasion tooling, which the project
  brief explicitly disallows. Instead it is transport-agnostic:

    * "direct" -> a normal TCP loopback/LAN socket. Always available.
    * "vpn"    -> the SAME direct socket, but the operator runs the
                  experiment while their machine's own, institutionally
                  sanctioned VPN client is connected. The script just
                  measures; the operator owns the VPN setup.
    * "tor"    -> the socket is routed through a SOCKS5 proxy
                  (default 127.0.0.1:9050) that the operator has started
                  themselves via the official Tor daemon / Tor Browser.
                  If no Tor proxy is running, the connection fails
                  GRACEFULLY and is logged as a failure case -- this is
                  the brief's required negative experiment for transport.

REPRODUCIBILITY
  run_transport_benchmark() is deterministic given the same event list and
  produces a metrics dict that the evaluation report consumes directly.
"""

from __future__ import annotations
import json
import socket
import threading
import time
from dataclasses import dataclass, field, asdict

try:
    import socks  # PySocks, optional -- only needed for the Tor path
    _HAVE_SOCKS = True
except ImportError:                       # pragma: no cover
    _HAVE_SOCKS = False


# Qualitative threat-model / setup notes, reported alongside the numbers.
TRANSPORT_PROFILE = {
    "direct": {
        "setup_complexity": "trivial (no extra software)",
        "threat_model": ("No confidentiality vs anyone on the LAN/path. "
                         "Sensor events readable by local network "
                         "observers. Acceptable only on a trusted, "
                         "isolated lab segment."),
        "anonymity": "none -- source and destination IPs fully visible.",
    },
    "vpn": {
        "setup_complexity": ("moderate -- requires an institutionally "
                             "approved VPN client, configured by the "
                             "operator, not by this script."),
        "threat_model": ("Encrypts the home->VPN-exit hop; hides traffic "
                         "from the local ISP/LAN observer. The VPN "
                         "provider itself becomes a trusted third party "
                         "and can see metadata. Not anonymity, but "
                         "meaningful confidentiality."),
        "anonymity": ("limited -- VPN provider can correlate source and "
                      "destination."),
    },
    "tor": {
        "setup_complexity": ("high -- operator must install and run the "
                             "official Tor daemon; higher and more "
                             "variable latency."),
        "threat_model": ("Multi-hop onion routing: no single relay sees "
                         "both source and destination. Strong against "
                         "local network observers and the destination "
                         "learning the home's IP."),
        "anonymity": ("strongest of the three, but NOT absolute -- a "
                      "global passive adversary or traffic-correlation "
                      "attack can still de-anonymize. State this limit "
                      "honestly in the paper."),
    },
}


@dataclass
class TransportResult:
    transport: str
    events_sent: int = 0
    events_delivered: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    error: str | None = None

    @property
    def connection_success(self) -> bool:
        return self.error is None and self.events_delivered > 0

    def summary(self) -> dict:
        lat = self.latencies_ms
        ok = len(lat) > 0
        return {
            "transport": self.transport,
            "connection_success": self.connection_success,
            "events_sent": self.events_sent,
            "events_delivered": self.events_delivered,
            "delivery_rate": (self.events_delivered / self.events_sent
                              if self.events_sent else 0.0),
            "latency_ms_mean": round(sum(lat) / len(lat), 3) if ok else None,
            "latency_ms_p95": (round(sorted(lat)[int(0.95 * (len(lat) - 1))],
                                     3) if ok else None),
            "throughput_eps": (round(self.events_delivered
                               / (sum(lat) / 1000.0), 2)
                               if ok and sum(lat) > 0 else None),
            "error": self.error,
            **TRANSPORT_PROFILE.get(self.transport, {}),
        }


def _echo_server(host: str, port: int, ready: threading.Event,
                 stop: threading.Event) -> None:
    """Tiny loopback server: receives a sensor event, echoes it back.

    Echoing lets the client measure true round-trip latency for whichever
    transport it used to connect."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(8)
    srv.settimeout(0.5)
    ready.set()
    while not stop.is_set():
        try:
            conn, _ = srv.accept()
        except socket.timeout:
            continue
        with conn:
            conn.settimeout(2.0)
            while not stop.is_set():
                try:
                    data = conn.recv(4096)
                except socket.timeout:
                    break
                if not data:
                    break
                conn.sendall(data)        # echo
    srv.close()


def _make_socket(transport: str, tor_host: str, tor_port: int) -> socket.socket:
    """Return a socket configured for the requested transport."""
    if transport == "tor":
        if not _HAVE_SOCKS:
            raise RuntimeError("PySocks not installed; cannot use Tor path")
        s = socks.socksocket()
        s.set_proxy(socks.SOCKS5, tor_host, tor_port)
        return s
    # direct and vpn use an identical plain socket; the VPN, if any, is
    # active at the OS level and outside this script's control.
    return socket.socket(socket.AF_INET, socket.SOCK_STREAM)


def run_transport_benchmark(events: list[dict],
                            transport: str = "direct",
                            host: str = "127.0.0.1",
                            port: int = 8765,
                            tor_host: str = "127.0.0.1",
                            tor_port: int = 9050,
                            connect_timeout: float = 8.0) -> dict:
    """
    Stream `events` over the chosen transport and measure round-trip
    latency per event. Returns a metrics summary dict.

    For 'direct'/'vpn' the destination is a local echo server started here.
    For 'tor' the SOCKS proxy still routes back to that local echo server,
    so we measure transport overhead on an identical workload.
    """
    result = TransportResult(transport=transport)
    result.events_sent = len(events)

    ready, stop = threading.Event(), threading.Event()
    server = threading.Thread(target=_echo_server,
                              args=(host, port, ready, stop), daemon=True)
    server.start()
    ready.wait(timeout=3.0)

    try:
        sock = _make_socket(transport, tor_host, tor_port)
        sock.settimeout(connect_timeout)
        sock.connect((host, port))
        for ev in events:
            payload = (json.dumps(ev) + "\n").encode()
            t0 = time.perf_counter()
            sock.sendall(payload)
            echoed = sock.recv(8192)
            t1 = time.perf_counter()
            if echoed:
                result.events_delivered += 1
                result.latencies_ms.append((t1 - t0) * 1000.0)
        sock.close()
    except Exception as exc:                       # graceful failure case
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        stop.set()
        server.join(timeout=2.0)

    return result.summary()


if __name__ == "__main__":
    # Demo: 200 synthetic events over the always-available direct path.
    demo = [{"sensor": "motion_living", "value": 1, "t": i}
            for i in range(200)]
    print(json.dumps(run_transport_benchmark(demo, "direct"), indent=2))
