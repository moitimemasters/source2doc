import { ProjectConfig } from "./project-types";

const GATEWAY_URL = process.env.GATEWAY_URL || "http://localhost:8003";

export class ProjectLoader {
    private static instance: ProjectLoader;
    private cachedProjects: ProjectConfig[] | null = null;

    private constructor() {}

    static getInstance(): ProjectLoader {
        if (!ProjectLoader.instance) {
            ProjectLoader.instance = new ProjectLoader();
        }
        return ProjectLoader.instance;
    }

    async loadRegistry() {
        const projects = await this.getAllProjects();
        return {
            projects,
            defaultProject: projects[0]?.id,
        };
    }

    async getProject(projectId: string): Promise<ProjectConfig | null> {
        const projects = await this.getAllProjects();
        return projects.find((p) => p.id === projectId) || null;
    }

    async getDefaultProject(): Promise<ProjectConfig | null> {
        const projects = await this.getAllProjects();
        return projects[0] || null;
    }

    async getAllProjects(): Promise<ProjectConfig[]> {
        console.log(
            "[ProjectLoader] Fetching bundles from gateway:",
            GATEWAY_URL,
        );

        try {
            const response = await fetch(
                `${GATEWAY_URL}/api/v1/docs/bundles?t=${Date.now()}`,
                {
                    headers: {
                        "Content-Type": "application/json",
                        "Cache-Control": "no-cache, no-store, must-revalidate",
                        Pragma: "no-cache",
                        Expires: "0",
                    },
                    cache: "no-store",
                },
            );

            if (!response.ok) {
                console.error("Failed to fetch bundles:", response.status);
                return [];
            }

            const data = await response.json();
            const bundles = data.bundles || [];
            console.log("[ProjectLoader] Received bundles:", bundles.length);

            const projects = bundles
                .filter((bundle: any) => {
                    const successful =
                        bundle.successful_pages_count ??
                        bundle.pages_count - (bundle.failed_pages_count || 0);
                    return successful > 0;
                })
                .map((bundle: any) => {
                    const createdDate = new Date(bundle.created_at);
                    const formattedDate = createdDate.toLocaleString("en-US", {
                        month: "short",
                        day: "numeric",
                        hour: "2-digit",
                        minute: "2-digit",
                    });

                    const totalPages = bundle.pages_count || 0;
                    const failedPages = bundle.failed_pages_count || 0;
                    const successfulPages =
                        bundle.successful_pages_count ?? totalPages - failedPages;
                    const pagesLabel =
                        failedPages > 0
                            ? `${successfulPages}/${totalPages} pages`
                            : `${totalPages} pages`;

                    // Prefer bundle.name (from task metadata), then repository name,
                    // then project_name (legacy), then fallback to short ID
                    const projectName =
                        bundle.name ||
                        bundle.repository?.name ||
                        bundle.project_name ||
                        `Project ${bundle.generation_id?.substring(0, 8) || bundle.id}`;

                    // Prefer bundle.description, then auto-generate from pages count
                    const projectDescription =
                        bundle.description ||
                        (bundle.repository?.git_url
                            ? `${bundle.repository.git_url}${bundle.repository.git_branch ? ` @ ${bundle.repository.git_branch}` : ""} · ${pagesLabel}`
                            : `Generated documentation · ${pagesLabel}`);

                    return {
                        id: bundle.generation_id, // Use generation_id (UUID) as project ID
                        name: `${projectName} (${formattedDate})`,
                        description: projectDescription,
                        version: bundle.generation_id?.substring(0, 8),
                        source: {
                            type: "gateway" as const,
                            bundleId: bundle.generation_id,
                        },
                        metadata: {
                            lastUpdated: bundle.created_at,
                            generationId: bundle.generation_id,
                            numericId: bundle.id, // Keep numeric ID for reference
                            repoId: bundle.repo_id,
                        },
                    };
                });

            console.log(
                "[ProjectLoader] Processed projects:",
                projects.map((p: ProjectConfig) => ({ id: p.id, name: p.name })),
            );
            // Don't cache - always return fresh data
            return projects;
        } catch (error) {
            console.error("Error loading projects from gateway:", error);
            return [];
        }
    }

    invalidateCache(): void {
        this.cachedProjects = null;
    }
}

export const projectLoader = ProjectLoader.getInstance();
