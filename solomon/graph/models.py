"""Graph visualization DTOs (API / UI / Agent 共有)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

GraphQueryType = Literal[
    "schema",
    "label",
    "relationship",
    "property",
    "neighborhood",
    "entity",
]


class GraphNodeDTO(BaseModel):
    id: str
    labels: list[str] = Field(default_factory=list)
    properties: dict[str, Any] = Field(default_factory=dict)
    caption: str = "Node"


class GraphEdgeDTO(BaseModel):
    id: str
    type: str
    source: str
    target: str
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphVisualization(BaseModel):
    nodes: list[GraphNodeDTO] = Field(default_factory=list)
    edges: list[GraphEdgeDTO] = Field(default_factory=list)
    truncated: bool = False
    cypher: str = ""
    query_type: GraphQueryType = "label"


class GraphSchemaResponse(BaseModel):
    node_labels: list[str] = Field(default_factory=list)
    relationship_types: list[str] = Field(default_factory=list)
    property_keys: list[str] = Field(default_factory=list)


class GraphQueryResponse(BaseModel):
    query_type: GraphQueryType
    cypher: str
    graph: GraphVisualization
    node_count: int = 0
    edge_count: int = 0
