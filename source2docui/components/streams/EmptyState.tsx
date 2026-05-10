import { FileText, Activity } from "lucide-react";

interface EmptyStateProps {
    isLoading: boolean;
}

export function EmptyState({ isLoading }: EmptyStateProps) {
    if (isLoading) {
        return (
            <div className="text-center py-12">
                <div className="animate-pulse">
                    <Activity className="h-12 w-12 mx-auto mb-4 text-muted-foreground" />
                    <p className="text-muted-foreground">Loading streams...</p>
                </div>
            </div>
        );
    }

    return (
        <div className="text-center py-12">
            <FileText className="h-12 w-12 mx-auto mb-4 text-muted-foreground" />
            <p className="text-muted-foreground">
                No active streams found. Start a documentation generation to see
                it here.
            </p>
        </div>
    );
}
