from typing import Literal

from pydantic import BaseModel, Field


class BundleExportRequest(BaseModel):
    bundle_id: int = Field(..., description="Bundle ID from database")
    generation_id: str = Field(..., description="Generation UUID")
    format: str = Field(..., description="Output format (nextra, sphinx, mkdocs, etc.)")
    channel: str = Field(default="bundler", description="PubSub channel for custom workers")
    s3_config: dict | None = Field(
        default=None,
        description="Optional S3 configuration override",
    )
    mermaid_render: Literal["fence", "svg", "png"] | None = Field(
        default=None,
        description=(
            "How to handle ```mermaid``` blocks in the bundle. "
            "'fence' keeps the source fence (themes with JS renderers handle it). "
            "'svg'/'png' pre-render diagrams via mermaid-cli and replace the "
            "fence with a static image reference. None lets the bundler pick a "
            "format-specific default (GFM/Sphinx → svg, MkDocs/Nextra → fence)."
        ),
    )


class BundleExportResponse(BaseModel):
    bundle_id: int
    generation_id: str
    format: str
    message: str
