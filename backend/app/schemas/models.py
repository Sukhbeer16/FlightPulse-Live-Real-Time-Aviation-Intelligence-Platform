"""Model catalog response contracts."""

from typing import Literal

from pydantic import BaseModel


class ModelMetrics(BaseModel):
    """Selected evaluation metrics for one documented dataset partition."""

    precision: float
    recall: float
    pr_auc: float
    roc_auc: float
    threshold: float


class ModelCatalogEntry(BaseModel):
    """Availability and provenance for one trained model artifact."""

    model_id: str
    algorithm: str
    task: Literal["delay_prediction", "anomaly_detection"]
    status: Literal["available", "unavailable"]
    artifact: str | None
    inference_supported: bool
    model_version: str | None
    training_period: str | None
    feature_count: int | None
    validation_metrics: ModelMetrics | None = None
    test_metrics: ModelMetrics | None = None
    reason: str | None = None


class ModelCatalogResponse(BaseModel):
    """Inventory of saved model artifacts and their supported use."""

    data_kind: Literal["model_catalog"] = "model_catalog"
    models: list[ModelCatalogEntry]
