"""Tools for the network latency investigation agent.

Three tools are provided:
1. get_link_metrics   - query real-time metrics of a network link
2. calculate_queue_delay - compute theoretical queue delay using M/M/1 model
3. analyze_delay_components - decompose total delay into propagation/transmission/queue/processing
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .models import DelayComponents, LinkConfig, LinkMetrics, MM1Result

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "sample_data.json"
_NETWORK_CACHE: dict[str, Any] | None = None
# The active scenario models the *current* state of the simulated network.
# It is configured externally (CLI / evaluation harness), never by the LLM.
_ACTIVE_SCENARIO: str = "congestion"


def set_active_scenario(name: str) -> None:
    """Set which simulated scenario the tools report as the live network state."""
    global _ACTIVE_SCENARIO
    data = _load_network_data()
    if name not in data.get("scenarios", {}):
        raise ValueError(
            f"Unknown scenario '{name}'. Available: {list(data.get('scenarios', {}).keys())}"
        )
    _ACTIVE_SCENARIO = name


def get_active_scenario() -> str:
    """Return the currently active scenario name."""
    return _ACTIVE_SCENARIO


def _load_network_data() -> dict[str, Any]:
    global _NETWORK_CACHE
    if _NETWORK_CACHE is None:
        _NETWORK_CACHE = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    return _NETWORK_CACHE


def get_link_config(link_id: str) -> LinkConfig | None:
    """Look up static link configuration by link_id."""
    data = _load_network_data()
    for link in data["topology"]["links"]:
        if link["id"] == link_id:
            return LinkConfig(
                id=link["id"],
                from_node=link["from"],
                to_node=link["to"],
                bandwidth_mbps=link["bandwidth_mbps"],
                length_km=link["length_km"],
                interface_type=link["interface_type"],
                propagation_speed_factor=link.get("propagation_speed_factor", 0.67),
            )
    return None


def get_scenario_metrics(scenario: str) -> dict[str, LinkMetrics] | None:
    """Load metrics for a given scenario name."""
    data = _load_network_data()
    scenarios = data.get("scenarios", {})
    if scenario not in scenarios:
        return None
    raw = scenarios[scenario]["link_metrics"]
    result: dict[str, LinkMetrics] = {}
    for link_id, m in raw.items():
        result[link_id] = LinkMetrics(
            utilization=m.get("utilization"),
            rtt_ms=m.get("rtt_ms"),
            packet_loss_percent=m.get("packet_loss_percent"),
            avg_queue_depth=m.get("avg_queue_depth"),
            peak_queue_depth=m.get("peak_queue_depth"),
            arrival_rate_pps=m.get("arrival_rate_pps"),
            avg_packet_size_bytes=m.get("avg_packet_size_bytes"),
        )
    return result


# ---------------------------------------------------------------------------
# Tool 1: get_link_metrics
# ---------------------------------------------------------------------------

def tool_get_link_metrics(link_id: str, scenario: str | None = None) -> dict[str, Any]:
    """Query real-time metrics for a specific network link.

    Args:
        link_id: The link identifier, e.g. 'link-dist-a-sw1'.
        scenario: Optional scenario override. When omitted, the currently
            active (live) scenario is used.

    Returns:
        A dict containing link config and real-time metrics.
    """
    config = get_link_config(link_id)
    if config is None:
        return {"error": f"Link '{link_id}' not found. Available links: {[l['id'] for l in _load_network_data()['topology']['links']]}"}

    scenario = scenario or _ACTIVE_SCENARIO
    metrics_map = get_scenario_metrics(scenario)
    if metrics_map is None:
        return {"error": f"Scenario '{scenario}' not found."}

    metrics = metrics_map.get(link_id)
    if metrics is None:
        return {"error": f"No metrics for link '{link_id}' in scenario '{scenario}'."}

    available_links = list(metrics_map.keys())

    result: dict[str, Any] = {
        "link_id": link_id,
        "from_node": config.from_node,
        "to_node": config.to_node,
        "bandwidth_mbps": config.bandwidth_mbps,
        "length_km": config.length_km,
        "interface_type": config.interface_type,
        "utilization": metrics.utilization,
        "rtt_ms": metrics.rtt_ms,
        "packet_loss_percent": metrics.packet_loss_percent,
        "avg_queue_depth": metrics.avg_queue_depth,
        "peak_queue_depth": metrics.peak_queue_depth,
        "arrival_rate_pps": metrics.arrival_rate_pps,
        "avg_packet_size_bytes": metrics.avg_packet_size_bytes,
        "_hint": {"available_links": available_links},
    }
    return result


# ---------------------------------------------------------------------------
# Tool 2: calculate_queue_delay
# ---------------------------------------------------------------------------

def tool_calculate_queue_delay(
    arrival_rate_pps: float,
    service_rate_pps: float,
    avg_packet_size_bytes: float = 800,
    bandwidth_mbps: float = 1000,
) -> dict[str, Any]:
    """Calculate theoretical queue delay using M/M/1 model.

    The M/M/1 model assumes Poisson arrivals and exponential service times
    with a single queue. It gives an upper-bound estimate of queue delay.

    Applicable conditions:
    - Traffic approximates Poisson process (many independent sources)
    - Single bottleneck link
    - Steady-state (arrival_rate < service_rate, i.e. rho < 1)

    Args:
        arrival_rate_pps: Packet arrival rate (packets per second), lambda.
        service_rate_pps: Service rate (packets per second), mu.
            Computed as bandwidth / avg_packet_size if not directly known.
        avg_packet_size_bytes: Average packet size in bytes (for reference).
        bandwidth_mbps: Link bandwidth in Mbps (for reference).

    Returns:
        M/M/1 queue analysis results.
    """
    if arrival_rate_pps <= 0:
        return {"error": "arrival_rate_pps must be positive."}
    if service_rate_pps <= 0:
        return {"error": "service_rate_pps must be positive."}

    rho = arrival_rate_pps / service_rate_pps

    if rho >= 1.0:
        return {
            "error": f"System is unstable! rho = {rho:.4f} >= 1. "
                     f"Arrival rate ({arrival_rate_pps:.0f} pps) >= service rate ({service_rate_pps:.0f} pps). "
                     f"The queue will grow indefinitely. This itself indicates severe congestion.",
            "utilization_rho": round(rho, 4),
            "is_stable": False,
        }

    # M/M/1 formulas
    L = rho / (1 - rho)          # avg packets in system
    Lq = rho ** 2 / (1 - rho)    # avg packets in queue
    W = L / arrival_rate_pps     # avg time in system (seconds)
    Wq = Lq / arrival_rate_pps   # avg time in queue (seconds)

    result = MM1Result(
        utilization=rho,
        avg_packets_in_system=L,
        avg_time_in_system_ms=W * 1000,
        avg_queue_length=Lq,
        avg_queue_delay_ms=Wq * 1000,
        is_stable=True,
    )

    output = result.to_dict()
    output["note"] = (
        "M/M/1 model assumes Poisson arrivals and exponential service. "
        "Real network delay may differ due to bursty traffic, multiple queues, "
        "or scheduling effects. Use as an approximation."
    )
    return output


# ---------------------------------------------------------------------------
# Tool 3: analyze_delay_components
# ---------------------------------------------------------------------------

def tool_analyze_delay_components(
    link_id: str,
    scenario: str | None = None,
    processing_delay_ms: float = 0.5,
) -> dict[str, Any]:
    """Decompose total delay on a link into propagation, transmission, queue, and processing.

    This tool uses link configuration and real-time metrics to compute:
    - Propagation delay = length / (speed_of_light * propagation_speed_factor)
    - Transmission delay = packet_size / bandwidth
    - Queue delay = estimated from M/M/1 model using observed arrival rate
    - Processing delay = router/switch processing (default 0.5ms, configurable)

    Args:
        link_id: The link identifier.
        scenario: Optional scenario override; defaults to the live scenario.
        processing_delay_ms: Estimated processing delay at each node (default 0.5ms).

    Returns:
        Delay decomposition with each component and comparison to observed RTT.
    """
    config = get_link_config(link_id)
    if config is None:
        return {"error": f"Link '{link_id}' not found."}

    scenario = scenario or _ACTIVE_SCENARIO
    metrics_map = get_scenario_metrics(scenario)
    if metrics_map is None:
        return {"error": f"Scenario '{scenario}' not found."}

    metrics = metrics_map.get(link_id)
    if metrics is None or not metrics.has_data():
        return {"error": f"Insufficient data for link '{link_id}' in scenario '{scenario}'."}

    # 1. Propagation delay
    speed_of_light_km_s = 299792.458  # km/s
    effective_speed = speed_of_light_km_s * config.propagation_speed_factor
    prop_delay_ms = (config.length_km / effective_speed) * 1000

    # 2. Transmission delay
    avg_pkt_bytes = metrics.avg_packet_size_bytes or 800
    bandwidth_bps = config.bandwidth_mbps * 1_000_000
    pkt_bits = avg_pkt_bytes * 8
    trans_delay_ms = (pkt_bits / bandwidth_bps) * 1000

    # 3. Queue delay (M/M/1 estimate)
    # Use observed utilization as rho for M/M/1 model.
    # This is more accurate than computing rho from arrival/service rate
    # because utilization already reflects actual traffic load including overhead.
    arrival_rate = metrics.arrival_rate_pps or 0
    service_rate = bandwidth_bps / (avg_pkt_bytes * 8)
    rho = metrics.utilization if metrics.utilization is not None else (arrival_rate / service_rate if service_rate > 0 else 0)

    if rho >= 1.0:
        queue_delay_ms = float("inf")
        queue_note = "Queue is unstable (rho >= 1). Delay is unbounded."
    elif rho > 0:
        # Derive effective service rate from observed utilization:
        # rho = arrival_rate / effective_mu => effective_mu = arrival_rate / rho
        # This accounts for all traffic (background, overhead, etc.) that the
        # theoretical bandwidth-based service rate doesn't capture.
        if arrival_rate > 0:
            effective_mu = arrival_rate / rho
        else:
            effective_mu = service_rate
        # M/M/1: Wq = rho / (mu * (1 - rho))
        Wq = rho / (effective_mu * (1 - rho))
        queue_delay_ms = Wq * 1000
        queue_note = f"M/M/1 estimate with rho={rho:.4f} (observed utilization), effective_mu={effective_mu:.0f} pps"
    else:
        queue_delay_ms = 0.0
        queue_note = "No traffic"

    # 4. Processing delay
    proc_delay_ms = processing_delay_ms

    # Total one-way delay
    total_delay_ms = prop_delay_ms + trans_delay_ms + queue_delay_ms + proc_delay_ms

    # Compare with observed RTT (one-way vs round-trip)
    observed_rtt_ms = metrics.rtt_ms
    estimated_rtt_ms = total_delay_ms * 2  # rough RTT estimate (there and back)
    rtt_ratio = None
    if observed_rtt_ms and observed_rtt_ms > 0:
        rtt_ratio = estimated_rtt_ms / observed_rtt_ms

    components = DelayComponents(
        propagation_delay_ms=prop_delay_ms,
        transmission_delay_ms=trans_delay_ms,
        queue_delay_ms=queue_delay_ms if queue_delay_ms != float("inf") else 999999.0,
        processing_delay_ms=proc_delay_ms,
        total_delay_ms=total_delay_ms if total_delay_ms != float("inf") else 999999.0,
    )

    return {
        "link_id": link_id,
        "scenario": scenario,
        "link_config": {
            "bandwidth_mbps": config.bandwidth_mbps,
            "length_km": config.length_km,
            "propagation_speed_factor": config.propagation_speed_factor,
        },
        "traffic_info": {
            "arrival_rate_pps": arrival_rate,
            "service_rate_pps": round(service_rate, 1),
            "utilization_rho": round(rho, 4),
            "avg_packet_size_bytes": avg_pkt_bytes,
        },
        "delay_components": components.to_dict(),
        "queue_note": queue_note,
        "comparison": {
            "estimated_one_way_ms": round(total_delay_ms, 3) if total_delay_ms != float("inf") else "unbounded",
            "estimated_rtt_ms": round(estimated_rtt_ms, 3) if estimated_rtt_ms != float("inf") else "unbounded",
            "observed_rtt_ms": observed_rtt_ms,
            "rtt_ratio_estimated_over_observed": round(rtt_ratio, 3) if rtt_ratio else None,
        },
        "interpretation_hint": (
            "If estimated_rtt is close to observed_rtt, queue delay dominates. "
            "If observed_rtt >> estimated_rtt, there may be additional delays "
            "(retransmissions, routing changes, or congestion at other links). "
            "If observed_rtt << estimated_rtt, check model assumptions."
        ),
    }


# ---------------------------------------------------------------------------
# Helper: list available links and scenarios
# ---------------------------------------------------------------------------

def tool_list_network() -> dict[str, Any]:
    """List all available links in the simulated network."""
    data = _load_network_data()
    links = [
        {"id": l["id"], "from": l["from"], "to": l["to"],
         "bandwidth_mbps": l["bandwidth_mbps"], "length_km": l["length_km"]}
        for l in data["topology"]["links"]
    ]
    return {"links": links}
