from source2doc.pipelines.codetour import CODETOUR
from source2doc.pipelines.docgen import DOCGEN
from source2doc.pipelines.prdoc import PRDOC
from source2doc.pipelines.types import Pipeline


PIPELINES: dict[str, Pipeline] = {
    DOCGEN.id: DOCGEN,
    CODETOUR.id: CODETOUR,
    PRDOC.id: PRDOC,
}


def get_pipeline(pipeline_id: str) -> Pipeline:
    if pipeline_id not in PIPELINES:
        raise KeyError(f"unknown pipeline {pipeline_id!r}")
    return PIPELINES[pipeline_id]


def list_pipelines() -> list[Pipeline]:
    return list(PIPELINES.values())


def validate_event(pipeline_id: str, event_type: str) -> None:
    pipeline = get_pipeline(pipeline_id)
    if not pipeline.has_event(event_type):
        raise ValueError(
            f"event {event_type!r} not registered in pipeline {pipeline_id!r}"
        )


def phase_for_event(pipeline_id: str, event_type: str) -> str | None:
    pipeline = PIPELINES.get(pipeline_id)
    if pipeline is None:
        return None
    return pipeline.phase_for_event(event_type)


def target_phase_for_event(pipeline_id: str, event_type: str) -> str | None:
    pipeline = PIPELINES.get(pipeline_id)
    if pipeline is None:
        return None
    return pipeline.target_phase_for_event(event_type)
