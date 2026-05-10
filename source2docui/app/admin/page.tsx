import Link from "next/link";

import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
} from "@/components/ui/card";
import { LogoutButton } from "@/components/admin/LogoutButton";

const sections = [
    {
        href: "/admin/presets",
        title: "Presets",
        description:
            "Server-side LLM/embeddings/qdrant configurations. End-users use the default preset; admins can override per request.",
    },
    {
        href: "/admin/generate",
        title: "Generate documentation",
        description:
            "Pick a repository and a preset, kick off a docgen pipeline.",
    },
    {
        href: "/admin/repos",
        title: "Repositories",
        description: "Clone, upload, and delete tracked repositories.",
    },
    {
        href: "/admin/health",
        title: "Component health",
        description:
            "Live status of Postgres, Redis, S3, Qdrant, and every worker — polled every 15 seconds.",
    },
    {
        href: "/admin/metrics",
        title: "Metrics",
        description:
            "Token usage, USD cost, and step latency across every generation. Filter by date range.",
    },
];

export default function AdminDashboardPage() {
    return (
        <div className="container mx-auto px-4 py-8">
            <div className="mx-auto max-w-5xl">
                <div className="mb-8 flex items-center justify-between">
                    <div>
                        <h1 className="text-3xl font-bold">Admin</h1>
                        <p className="text-muted-foreground">
                            Manage server-side configuration and trigger expensive operations.
                        </p>
                    </div>
                    <LogoutButton />
                </div>
                <div className="grid gap-4 md:grid-cols-3">
                    {sections.map((section) => (
                        <Link key={section.href} href={section.href}>
                            <Card className="h-full transition-colors hover:border-primary">
                                <CardHeader>
                                    <CardTitle>{section.title}</CardTitle>
                                </CardHeader>
                                <CardContent>
                                    <CardDescription>
                                        {section.description}
                                    </CardDescription>
                                </CardContent>
                            </Card>
                        </Link>
                    ))}
                </div>
            </div>
        </div>
    );
}
