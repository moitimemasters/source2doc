import { z } from "zod";

export const StreamInfoSchema = z.object({
    stream_id: z.string(),
    pipeline_id: z.string().default("docgen"),
    event_count: z.number(),
    last_event_id: z.string().nullable(),
    name: z.string().nullable().optional(),
    description: z.string().nullable().optional(),
    status: z.string().nullable().optional(),
    repo_id: z.string().nullable().optional(),
    repository: z
        .object({
            name: z.string(),
            source_type: z.string(),
            git_url: z.string().nullable().optional(),
            git_branch: z.string().nullable().optional(),
        })
        .nullable()
        .optional(),
    created_at: z.string().nullable().optional(),
    started_at: z.string().nullable().optional(),
    completed_at: z.string().nullable().optional(),
});

export const StreamListResponseSchema = z.object({
    streams: z.array(StreamInfoSchema),
});

export const StreamEventDataSchema = z.record(z.unknown());

export const StreamEventSchema = z.object({
    id: z.string(),
    type: z.string(),
    data: StreamEventDataSchema,
    phase: z.string().nullable().optional(),
    kind: z.string().nullable().optional(),
    trace_id: z.string().nullable().optional(),
});

export const GenerationRequestedEventSchema = z.object({
    type: z.literal("generation.requested"),
    data: z.object({
        generation_id: z.string(),
    }),
});

export const IngestStartedEventSchema = z.object({
    type: z.literal("ingest.started"),
    data: z.object({
        files_count: z.number(),
    }),
});

export const ChunkCreatedEventSchema = z.object({
    type: z.literal("chunk.created"),
    data: z.object({
        file: z.string(),
    }),
});

export const IngestCompletedEventSchema = z.object({
    type: z.literal("ingest.completed"),
    data: z.object({
        generation_id: z.string(),
    }),
});

export const IndexStartedEventSchema = z.object({
    type: z.literal("index.started"),
    data: z.object({
        chunks_count: z.number(),
    }),
});

export const EmbeddingsBatchEventSchema = z.object({
    type: z.literal("embeddings.batch"),
    data: z.object({
        processed: z.number(),
        total: z.number(),
    }),
});

export const EmbeddingsGeneratedEventSchema = z.object({
    type: z.literal("embeddings.generated"),
    data: z.object({
        count: z.number(),
    }),
});

export const IndexCompletedEventSchema = z.object({
    type: z.literal("index.completed"),
    data: z.object({
        generation_id: z.string(),
    }),
});

export const PlanCreatedEventSchema = z.object({
    type: z.literal("plan.created"),
    data: z.object({
        generation_id: z.string(),
    }),
});

export const DocIndexCreatedEventSchema = z.object({
    type: z.literal("doc.index.created"),
    data: z.object({
        generation_id: z.string(),
    }),
});

export const PageWriteRequestedEventSchema = z.object({
    type: z.literal("page.write_requested"),
    data: z.object({
        generation_id: z.string(),
    }),
});

export const PageWrittenEventSchema = z.object({
    type: z.literal("page.written"),
    data: z.object({
        generation_id: z.string(),
    }),
});

export const PageReviewedEventSchema = z.object({
    type: z.literal("page.reviewed"),
    data: z.object({
        generation_id: z.string(),
    }),
});

export const PageRevisionRequestedEventSchema = z.object({
    type: z.literal("page.revision_requested"),
    data: z.object({
        generation_id: z.string(),
    }),
});

export const PageCompletedEventSchema = z.object({
    type: z.literal("page.completed"),
    data: z.object({
        generation_id: z.string(),
    }),
});

export const DocPageCreatedEventSchema = z.object({
    type: z.literal("doc.page.created"),
    data: z.object({
        generation_id: z.string(),
    }),
});

export const GenerationCompletedEventSchema = z.object({
    type: z.literal("generation.completed"),
    data: z.object({
        generation_id: z.string(),
    }),
});

export const PageFailedEventSchema = z.object({
    type: z.literal("page.failed"),
    data: z.object({
        generation_id: z.string(),
        page_id: z.string().optional(),
        error: z.string().optional(),
        error_type: z.string().optional(),
    }),
});

export const DocPageFailedEventSchema = z.object({
    type: z.literal("doc.page.failed"),
    data: z.object({
        generation_id: z.string(),
        page_id: z.string().optional(),
        error: z.string().optional(),
    }),
});

export const IngestFailedEventSchema = z.object({
    type: z.literal("ingest.failed"),
    data: z.object({
        generation_id: z.string(),
        reason: z.string().optional(),
        files_count: z.number().optional(),
        chunks_count: z.number().optional(),
    }),
});

export const TaskFailedEventSchema = z.object({
    type: z.literal("task.failed"),
    data: z.object({
        generation_id: z.string(),
        error: z.string().optional(),
        error_type: z.string().optional(),
        attempts: z.number().optional(),
    }),
});

export type StreamInfo = z.infer<typeof StreamInfoSchema>;
export type StreamListResponse = z.infer<typeof StreamListResponseSchema>;
export type StreamEvent = z.infer<typeof StreamEventSchema>;
export type GenerationRequestedEvent = z.infer<
    typeof GenerationRequestedEventSchema
>;
export type IngestStartedEvent = z.infer<typeof IngestStartedEventSchema>;
export type ChunkCreatedEvent = z.infer<typeof ChunkCreatedEventSchema>;
export type IngestCompletedEvent = z.infer<typeof IngestCompletedEventSchema>;
export type IndexStartedEvent = z.infer<typeof IndexStartedEventSchema>;
export type EmbeddingsBatchEvent = z.infer<typeof EmbeddingsBatchEventSchema>;
export type EmbeddingsGeneratedEvent = z.infer<
    typeof EmbeddingsGeneratedEventSchema
>;
export type IndexCompletedEvent = z.infer<typeof IndexCompletedEventSchema>;
export type PlanCreatedEvent = z.infer<typeof PlanCreatedEventSchema>;
export type DocIndexCreatedEvent = z.infer<typeof DocIndexCreatedEventSchema>;
export type PageWriteRequestedEvent = z.infer<
    typeof PageWriteRequestedEventSchema
>;
export type PageWrittenEvent = z.infer<typeof PageWrittenEventSchema>;
export type PageReviewedEvent = z.infer<typeof PageReviewedEventSchema>;
export type PageRevisionRequestedEvent = z.infer<
    typeof PageRevisionRequestedEventSchema
>;
export type PageCompletedEvent = z.infer<typeof PageCompletedEventSchema>;
export type DocPageCreatedEvent = z.infer<typeof DocPageCreatedEventSchema>;
export type GenerationCompletedEvent = z.infer<
    typeof GenerationCompletedEventSchema
>;
