import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
    Loader2,
    Database,
    RefreshCw,
    Copy,
    CheckCircle2,
    AlertCircle,
    GitBranch,
    Upload,
    Trash2,
} from "lucide-react";
import { RepositoryInfo } from "@/lib/repos/schema";

interface RepositoryListViewProps {
    repositories: RepositoryInfo[];
    loading: boolean;
    error: string | null;
    copiedId: string | null;
    deletingId: string | null;
    onRefresh: () => void;
    onCopy: (repoId: string) => void;
    onDelete: (repoId: string, repoName: string) => void;
}

export function RepositoryListView({
    repositories,
    loading,
    error,
    copiedId,
    deletingId,
    onRefresh,
    onCopy,
    onDelete,
}: RepositoryListViewProps) {
    if (loading) {
        return (
            <Card>
                <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                        <Database className="h-5 w-5" />
                        Repositories
                    </CardTitle>
                    <CardDescription>
                        Loading repositories...
                    </CardDescription>
                </CardHeader>
                <CardContent>
                    <div className="flex items-center justify-center py-8">
                        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                    </div>
                </CardContent>
            </Card>
        );
    }

    return (
        <Card>
            <CardHeader>
                <div className="flex items-center justify-between">
                    <div>
                        <CardTitle className="flex items-center gap-2">
                            <Database className="h-5 w-5" />
                            Repositories
                        </CardTitle>
                        <CardDescription>
                            Available repositories for documentation generation
                        </CardDescription>
                    </div>
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={onRefresh}
                        disabled={loading}
                    >
                        <RefreshCw
                            className={`h-4 w-4 mr-2 ${loading ? "animate-spin" : ""}`}
                        />
                        Refresh
                    </Button>
                </div>
            </CardHeader>
            <CardContent>
                {error && (
                    <Alert variant="destructive" className="mb-4">
                        <AlertCircle className="h-4 w-4" />
                        <AlertDescription>{error}</AlertDescription>
                    </Alert>
                )}

                {repositories.length === 0 ? (
                    <div className="text-center py-12">
                        <Database className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
                        <p className="text-muted-foreground mb-2">
                            No repositories found
                        </p>
                        <p className="text-sm text-muted-foreground">
                            Upload a repository to get started
                        </p>
                    </div>
                ) : (
                    <div className="space-y-4">
                        <div className="flex items-center justify-between mb-4">
                            <Badge variant="secondary" className="text-sm">
                                {repositories.length}{" "}
                                {repositories.length === 1
                                    ? "repository"
                                    : "repositories"}
                            </Badge>
                        </div>

                        <div className="grid gap-3">
                            {repositories.map((repo) => (
                                <div
                                    key={repo.repo_id}
                                    className="flex items-center justify-between p-4 border rounded-lg hover:bg-muted/50 transition-colors"
                                >
                                    <div className="flex items-start gap-3 flex-1 min-w-0">
                                        {repo.source_type === "git" ? (
                                            <GitBranch className="h-4 w-4 text-muted-foreground flex-shrink-0 mt-1" />
                                        ) : (
                                            <Upload className="h-4 w-4 text-muted-foreground flex-shrink-0 mt-1" />
                                        )}
                                        <div className="min-w-0 flex-1">
                                            <div className="flex items-center gap-2 flex-wrap">
                                                <span className="font-medium text-sm truncate">
                                                    {repo.name}
                                                </span>
                                                <Badge
                                                    variant="outline"
                                                    className="text-xs flex-shrink-0"
                                                >
                                                    {repo.source_type}
                                                </Badge>
                                            </div>
                                            {repo.description && (
                                                <p className="text-xs text-muted-foreground mt-0.5 truncate">
                                                    {repo.description}
                                                </p>
                                            )}
                                            {repo.git_url && (
                                                <p className="text-xs text-muted-foreground mt-0.5 truncate">
                                                    {repo.git_url}
                                                    {repo.git_branch && (
                                                        <span className="ml-1 text-primary">
                                                            @{repo.git_branch}
                                                        </span>
                                                    )}
                                                </p>
                                            )}
                                            <code className="text-xs font-mono text-muted-foreground/70 mt-1 block truncate">
                                                {repo.repo_id}
                                            </code>
                                        </div>
                                    </div>
                                    <div className="flex items-center gap-1 flex-shrink-0 ml-2">
                                        <Button
                                            variant="ghost"
                                            size="sm"
                                            onClick={() => onCopy(repo.repo_id)}
                                        >
                                            {copiedId === repo.repo_id ? (
                                                <>
                                                    <CheckCircle2 className="h-4 w-4 mr-2 text-green-600" />
                                                    Copied
                                                </>
                                            ) : (
                                                <>
                                                    <Copy className="h-4 w-4 mr-2" />
                                                    Copy ID
                                                </>
                                            )}
                                        </Button>
                                        <Button
                                            variant="ghost"
                                            size="sm"
                                            onClick={() =>
                                                onDelete(repo.repo_id, repo.name)
                                            }
                                            disabled={deletingId === repo.repo_id}
                                            aria-label={`Delete ${repo.name}`}
                                            className="text-destructive hover:text-destructive"
                                        >
                                            {deletingId === repo.repo_id ? (
                                                <Loader2 className="h-4 w-4 animate-spin" />
                                            ) : (
                                                <Trash2 className="h-4 w-4" />
                                            )}
                                        </Button>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                )}
            </CardContent>
        </Card>
    );
}
