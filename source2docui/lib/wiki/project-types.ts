import { z } from "zod";

const ProjectMetadataSchema = z.object({
    homepage: z.string().url().optional(),
    repository: z.string().url().optional(),
    documentation: z.string().url().optional(),
    tags: z.array(z.string()).optional(),
    categories: z.array(z.string()).optional(),
    lastUpdated: z.string().datetime().optional(),
    authors: z.array(z.string()).optional(),
});

const FileSystemSourceSchema = z.object({
    type: z.literal("filesystem"),
    dataPath: z.string(),
    navigationPath: z.string().optional(),
});

const ApiAuthSchema = z.object({
    type: z.enum(["bearer", "basic", "apikey"]),
    token: z.string().optional(),
    username: z.string().optional(),
    password: z.string().optional(),
    apiKey: z.string().optional(),
});

const ApiSourceSchema = z.object({
    type: z.literal("api"),
    baseUrl: z.string().url(),
    auth: ApiAuthSchema.optional(),
    endpoints: z.object({
        content: z.string(),
        navigation: z.string(),
    }),
});

const GatewaySourceSchema = z.object({
    type: z.literal("gateway"),
    bundleId: z.string(),
});

const ProjectSourceSchema = z.discriminatedUnion("type", [
    FileSystemSourceSchema,
    ApiSourceSchema,
    GatewaySourceSchema,
]);

export const ProjectConfigSchema = z.object({
    id: z.string(),
    name: z.string(),
    description: z.string().optional(),
    logo: z.string().optional(),
    version: z.string().optional(),
    source: ProjectSourceSchema,
    navigation: z.string().optional(),
    metadata: ProjectMetadataSchema.optional(),
});

export const ProjectRegistrySchema = z.object({
    projects: z.array(ProjectConfigSchema),
    defaultProject: z.string().optional(),
});

export type ProjectMetadata = z.infer<typeof ProjectMetadataSchema>;
export type FileSystemSource = z.infer<typeof FileSystemSourceSchema>;
export type ApiSource = z.infer<typeof ApiSourceSchema>;
export type GatewaySource = z.infer<typeof GatewaySourceSchema>;
export type ProjectSource = z.infer<typeof ProjectSourceSchema>;
export type ProjectConfig = z.infer<typeof ProjectConfigSchema>;
export type ProjectRegistry = z.infer<typeof ProjectRegistrySchema>;

export const ProjectContextSchema = z.object({
    projectId: z.string(),
    config: ProjectConfigSchema,
});

export type ProjectContext = z.infer<typeof ProjectContextSchema>;

export const ProjectListItemSchema = z.object({
    id: z.string(),
    name: z.string(),
    description: z.string().optional(),
    logo: z.string().optional(),
    version: z.string().optional(),
});

export type ProjectListItem = z.infer<typeof ProjectListItemSchema>;
