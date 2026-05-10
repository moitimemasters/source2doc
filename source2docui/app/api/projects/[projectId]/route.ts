import { NextResponse } from "next/server";
import { projectLoader } from "@/lib/wiki/project-loader";

export async function GET(
    request: Request,
    { params }: { params: Promise<{ projectId: string }> },
) {
    try {
        const { projectId } = await params;
        const project = await projectLoader.getProject(projectId);

        if (!project) {
            return NextResponse.json(
                { error: "Project not found" },
                { status: 404 },
            );
        }

        return NextResponse.json({
            id: project.id,
            name: project.name,
            description: project.description,
            logo: project.logo,
            version: project.version,
            metadata: project.metadata,
        });
    } catch (error) {
        console.error("Failed to load project:", error);
        return NextResponse.json(
            { error: "Failed to load project" },
            { status: 500 },
        );
    }
}
