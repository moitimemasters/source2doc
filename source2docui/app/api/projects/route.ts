import { NextResponse } from "next/server";
import { projectLoader } from "@/lib/wiki/project-loader";
import { ProjectListItemSchema } from "@/lib/wiki/project-types";
import { z } from "zod";

const ProjectsResponseSchema = z.object({
    projects: z.array(ProjectListItemSchema),
    defaultProject: z.string().optional(),
});

export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function GET() {
    console.log('[API /api/projects] GET request received at', new Date().toISOString());
    try {
        projectLoader.invalidateCache();
        console.log('[API /api/projects] Cache invalidated, loading registry...');
        const registry = await projectLoader.loadRegistry();
        console.log('[API /api/projects] Registry loaded, projects count:', registry.projects.length);

        const projects = registry.projects.map((p) => ({
            id: p.id,
            name: p.name,
            description: p.description,
            logo: p.logo,
            version: p.version,
        }));

        const response = ProjectsResponseSchema.parse({
            projects,
            defaultProject: registry.defaultProject,
        });

        return NextResponse.json(response);
    } catch (error) {
        console.error("Failed to load projects:", error);
        return NextResponse.json(
            { error: "Failed to load projects" },
            { status: 500 },
        );
    }
}
