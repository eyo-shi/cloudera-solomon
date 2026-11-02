"""Apache Ossie 本家形式 (core-spec 0.2 / 0.1.x semantic_model 包み) の Pydantic モデル。"""

from __future__ import annotations

from typing import Annotated, Any, Optional

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator


class CustomExtension(BaseModel):
    model_config = ConfigDict(extra="allow")

    vendor_name: str
    data: str = ""

    @model_validator(mode="before")
    @classmethod
    def _coerce_data(cls, value: Any) -> Any:
        if isinstance(value, dict) and isinstance(value.get("data"), dict):
            import json

            value = dict(value)
            value["data"] = json.dumps(value["data"], ensure_ascii=False)
        return value


class AIContext(BaseModel):
    model_config = ConfigDict(extra="allow")

    instructions: Optional[str] = None
    synonyms: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _coerce_string(cls, value: Any) -> Any:
        if isinstance(value, str):
            return {"instructions": value}
        return value


def _coerce_ai_context(value: Any) -> AIContext | None:
    if value is None:
        return None
    if isinstance(value, AIContext):
        return value
    return AIContext.model_validate(value)


AiContextOptional = Annotated[Optional[AIContext], BeforeValidator(_coerce_ai_context)]


class OssieExpression(BaseModel):
    model_config = ConfigDict(extra="allow")

    sql: Optional[str] = None
    dialects: list[dict[str, Any]] = Field(default_factory=list)


class OssieFieldDimension(BaseModel):
    model_config = ConfigDict(extra="allow")

    is_time: bool = False


class OssieField(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    expression: Optional[OssieExpression | str] = None
    dimension: Optional[OssieFieldDimension | bool] = None
    label: Optional[str] = None
    description: Optional[str] = None
    datatype: Optional[str] = None
    ai_context: AiContextOptional = None
    custom_extensions: list[CustomExtension] = Field(default_factory=list)

    def is_dimension(self) -> bool:
        if self.dimension is True:
            return True
        if isinstance(self.dimension, OssieFieldDimension):
            return True
        if isinstance(self.dimension, dict):
            return True
        return False


class OssieMetric(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    expression: Optional[str | OssieExpression] = None
    description: Optional[str] = None
    datatype: Optional[str] = None
    ai_context: AiContextOptional = None
    custom_extensions: list[CustomExtension] = Field(default_factory=list)


class OssieDataset(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    source: Optional[str | dict[str, Any]] = None
    primary_key: Optional[list[str] | str] = None
    unique_keys: list[Any] = Field(default_factory=list)
    description: Optional[str] = None
    ai_context: AiContextOptional = None
    fields: list[OssieField] = Field(default_factory=list)
    metrics: list[OssieMetric] = Field(default_factory=list)
    custom_extensions: list[CustomExtension] = Field(default_factory=list)


class OssieRelationship(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[str] = None
    from_: Optional[str] = Field(None, alias="from")
    to: Optional[str] = None
    from_columns: list[str] = Field(default_factory=list)
    to_columns: list[str] = Field(default_factory=list)
    ai_context: AiContextOptional = None
    custom_extensions: list[CustomExtension] = Field(default_factory=list)


class OssieSemanticModel(BaseModel):
    """1 ファイル = 1 セマンティックモデル。"""

    model_config = ConfigDict(extra="allow")

    version: Optional[str] = None
    name: str
    description: Optional[str] = None
    ai_context: AiContextOptional = None
    datasets: list[OssieDataset] = Field(default_factory=list)
    relationships: list[OssieRelationship] = Field(default_factory=list)
    metrics: list[OssieMetric] = Field(default_factory=list)
    custom_extensions: list[CustomExtension] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _name_nonempty(cls, v: str) -> str:
        if not (v or "").strip():
            raise ValueError("model name is required")
        return v.strip()


def parse_models_from_yaml(raw: Any) -> list[OssieSemanticModel]:
    """YAML ルートから 1 件以上の :class:`OssieSemanticModel` を得る。"""
    if raw is None:
        return []
    if isinstance(raw, list):
        return [OssieSemanticModel.model_validate(item) for item in raw]
    if not isinstance(raw, dict):
        raise ValueError("semantic YAML root must be a mapping or list")
    if "semantic_model" in raw:
        wrapped = raw["semantic_model"]
        if isinstance(wrapped, list):
            return [OssieSemanticModel.model_validate(item) for item in wrapped]
        return [OssieSemanticModel.model_validate(wrapped)]
    return [OssieSemanticModel.model_validate(raw)]


def dataset_source_ref(source: Optional[str | dict[str, Any]]) -> Optional[str]:
    """``catalog.schema.table`` 形式の参照文字列、または None。"""
    if source is None:
        return None
    if isinstance(source, str):
        text = source.strip()
        if text.count(".") >= 2 and " " not in text:
            return text
        return None
    if isinstance(source, dict):
        for key in ("table", "ref", "name"):
            v = source.get(key)
            if isinstance(v, str) and v.count(".") >= 2:
                return v.strip()
        cat = source.get("catalog")
        schema = source.get("schema")
        table = source.get("table")
        if all(isinstance(x, str) for x in (cat, schema, table)):
            return f"{cat}.{schema}.{table}"
    return None


def dataset_fq_name(model_name: str, dataset: OssieDataset) -> str:
    ref = dataset_source_ref(dataset.source)
    if ref:
        return ref
    return f"{model_name}.{dataset.name}"


__all__ = [
    "AIContext",
    "CustomExtension",
    "OssieDataset",
    "OssieExpression",
    "OssieField",
    "OssieMetric",
    "OssieRelationship",
    "OssieSemanticModel",
    "dataset_fq_name",
    "dataset_source_ref",
    "parse_models_from_yaml",
]
