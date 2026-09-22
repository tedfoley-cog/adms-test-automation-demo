"""Topology processing for the distribution network model."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from .models import Feeder, NetworkModel, Section, Switch

DEFAULT_MODEL_PATH = Path(__file__).resolve().parent.parent / "data" / "feeder_model.json"


def load_network(path: Path | None = None) -> NetworkModel:
    source = path or DEFAULT_MODEL_PATH
    with source.open(encoding="utf-8") as handle:
        return NetworkModel.model_validate(json.load(handle))


def get_feeder(network: NetworkModel, feeder_mrid: str) -> Feeder:
    for feeder in network.feeders:
        if feeder.mrid == feeder_mrid:
            return feeder
    raise KeyError(f"unknown feeder {feeder_mrid}")


def adjacency(feeder: Feeder) -> dict[str, list[tuple[str, str]]]:
    """Node -> list of (neighbour node, element mRID) for closed elements only."""
    graph: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for section in feeder.sections:
        graph[section.from_node].append((section.to_node, section.mrid))
        graph[section.to_node].append((section.from_node, section.mrid))
    for switch in feeder.switches:
        if switch.open:
            continue
        graph[switch.from_node].append((switch.to_node, switch.mrid))
        graph[switch.to_node].append((switch.from_node, switch.mrid))
    return graph


def energised_nodes(feeder: Feeder, source_node: str | None = None) -> set[str]:
    """Nodes reachable from the source through closed elements."""
    graph = adjacency(feeder)
    start = source_node or feeder.source_node
    seen: set[str] = set()
    stack = [start]
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        for neighbour, _ in graph.get(node, []):
            if neighbour not in seen:
                stack.append(neighbour)
    return seen


def sections_downstream_of(feeder: Feeder, node: str) -> list[Section]:
    """Sections reachable from `node` while walking away from the source."""
    graph = adjacency(feeder)
    by_mrid = {section.mrid: section for section in feeder.sections}
    seen_nodes = {feeder.source_node} if node != feeder.source_node else set()
    result: list[Section] = []
    stack = [node]
    while stack:
        current = stack.pop()
        if current in seen_nodes:
            continue
        seen_nodes.add(current)
        for neighbour, element in graph.get(current, []):
            if element in by_mrid and by_mrid[element] not in result:
                result.append(by_mrid[element])
            if neighbour not in seen_nodes:
                stack.append(neighbour)
    return result


def switch_by_mrid(feeder: Feeder, mrid: str) -> Switch:
    for switch in feeder.switches:
        if switch.mrid == mrid:
            return switch
    raise KeyError(f"unknown switch {mrid}")


def customers_out(feeder: Feeder) -> int:
    live = energised_nodes(feeder)
    return sum(section.customers for section in feeder.sections if section.to_node not in live)


def load_on_nodes(feeder: Feeder, nodes: set[str]) -> float:
    return sum(section.load_kw for section in feeder.sections if section.to_node in nodes)
