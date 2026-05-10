interface ErrorStateProps {
    error: string;
}

export function ErrorState({ error }: ErrorStateProps) {
    return (
        <div className="min-h-screen bg-gradient-to-b from-background to-muted/20">
            <div className="container mx-auto px-4 py-16">
                <div className="max-w-4xl mx-auto">
                    <div className="text-center">
                        <h1 className="text-4xl font-bold tracking-tight mb-4">
                            Documentation Streams
                        </h1>
                        <div className="text-destructive mt-8">Error: {error}</div>
                    </div>
                </div>
            </div>
        </div>
    );
}
