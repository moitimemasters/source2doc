import Link from "next/link";
import { projectLoader } from "@/lib/wiki/project-loader";
import { Card, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { BookOpen, ExternalLink, Activity, Package, Sparkles } from "lucide-react";

export default async function Home() {
    const registry = await projectLoader.loadRegistry();
    const projects = registry.projects;

    return (
        <main className="min-h-screen bg-gradient-to-b from-background to-muted/20">
            <div className="container mx-auto px-4 py-16">
                <div className="max-w-4xl mx-auto">
                    <div className="text-center mb-12">
                        <h1 className="text-4xl font-bold tracking-tight mb-4">
                            Documentation Hub
                        </h1>
                        <p className="text-xl text-muted-foreground mb-6">
                            Browse documentation for all projects
                        </p>
                        <div className="flex flex-wrap gap-4 justify-center">
                            <Link
                                href="/admin/generate"
                                className="inline-flex items-center gap-2 px-6 py-3 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
                            >
                                <Sparkles className="h-5 w-5" />
                                Generate Documentation
                            </Link>
                            <Link
                                href="/streams"
                                className="inline-flex items-center gap-2 px-6 py-3 bg-secondary text-secondary-foreground rounded-lg hover:bg-secondary/90 transition-colors"
                            >
                                <Activity className="h-5 w-5" />
                                Monitor Generation Streams
                            </Link>
                            <Link
                                href="/bundles"
                                className="inline-flex items-center gap-2 px-6 py-3 bg-secondary text-secondary-foreground rounded-lg hover:bg-secondary/90 transition-colors"
                            >
                                <Package className="h-5 w-5" />
                                Export Bundles
                            </Link>
                        </div>
                    </div>

                    <div className="grid gap-6 md:grid-cols-2">
                        {projects.map((project) => (
                            <Link
                                key={project.id}
                                href={`/wiki/${project.id}`}
                                className="group"
                            >
                                <Card className="h-full transition-all hover:shadow-lg hover:border-primary/50">
                                    <CardHeader>
                                        <div className="flex items-start justify-between mb-2">
                                            <div className="flex items-center gap-2">
                                                <BookOpen className="h-5 w-5 text-primary" />
                                                <CardTitle className="group-hover:text-primary transition-colors">
                                                    {project.name}
                                                </CardTitle>
                                            </div>
                                            <ExternalLink className="h-4 w-4 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" />
                                        </div>

                                        {project.description && (
                                            <CardDescription className="text-base">
                                                {project.description}
                                            </CardDescription>
                                        )}

                                        <div className="flex flex-wrap gap-2 mt-4">
                                            {project.version && (
                                                <Badge variant="secondary">
                                                    v{project.version}
                                                </Badge>
                                            )}
                                            {project.metadata?.tags?.slice(0, 3).map((tag) => (
                                                <Badge key={tag} variant="outline">
                                                    {tag}
                                                </Badge>
                                            ))}
                                        </div>
                                    </CardHeader>
                                </Card>
                            </Link>
                        ))}
                    </div>

                    {projects.length === 0 && (
                        <div className="text-center py-12 space-y-3">
                            <p className="text-muted-foreground">
                                No documentation generated yet.
                            </p>
                            <p className="text-sm text-muted-foreground">
                                Click <span className="font-medium">Generate Docs</span> in the
                                top bar to start a new generation, or open{" "}
                                <Link
                                    href="/streams"
                                    className="underline underline-offset-2 hover:text-foreground"
                                >
                                    Streams
                                </Link>{" "}
                                to watch one already in progress.
                            </p>
                        </div>
                    )}
                </div>
            </div>
        </main>
    );
}
