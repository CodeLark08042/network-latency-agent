"""Data models for the network latency investigation agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LinkConfig:
    """Static configuration of a network link."""
    id: str
    from_node: str
    to_node: str
    bandwidth_mbps: float
    length_km: float
    interface_type: str
    propagation_speed_factor: float = 0.67  # fraction of speed of light


@dataclass
class LinkMetrics:
    """Real-time metrics of a network link."""
    utilization: float | None = None          # 0.0 ~ 1.0
    rtt_ms: float | None = None               # round-trip time in ms
    packet_loss_percent: float | None = None  # percentage
    avg_queue_depth: float | None = None      # average number of packets in queue
    peak_queue_depth: float | None = None     # peak queue depth
    arrival_rate_pps: float | None = None     # packets per second
    avg_packet_size_bytes: float | None = None

    def has_data(self) -> bool:
        return self.utilization is not None and self.rtt_ms is not None


@dataclass
class DelayComponents:
    """Decomposed delay components for a link."""
    propagation_delay_ms: float = 0.0
    transmission_delay_ms: float = 0.0
    queue_delay_ms: float = 0.0
    processing_delay_ms: float = 0.0
    total_delay_ms: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {
            "propagation_delay_ms": round(self.propagation_delay_ms, 3),
            "transmission_delay_ms": round(self.transmission_delay_ms, 3),
            "queue_delay_ms": round(self.queue_delay_ms, 3),
            "processing_delay_ms": round(self.processing_delay_ms, 3),
            "total_delay_ms": round(self.total_delay_ms, 3),
        }


@dataclass
class MM1Result:
    """M/M/1 queue model result."""
    utilization: float           # rho = lambda / mu
    avg_packets_in_system: float  # L = rho / (1 - rho)
    avg_time_in_system_ms: float  # W = L / lambda, converted to ms
    avg_queue_length: float       # Lq = rho^2 / (1 - rho)
    avg_queue_delay_ms: float     # Wq = Lq / lambda, converted to ms
    is_stable: bool               # rho < 1 ?

    def to_dict(self) -> dict[str, Any]:
        return {
            "utilization_rho": round(self.utilization, 4),
            "avg_packets_in_system_L": round(self.avg_packets_in_system, 2),
            "avg_time_in_system_ms_W": round(self.avg_time_in_system_ms, 3),
            "avg_queue_length_Lq": round(self.avg_queue_length, 2),
            "avg_queue_delay_ms_Wq": round(self.avg_queue_delay_ms, 3),
            "is_stable": self.is_stable,
        }
