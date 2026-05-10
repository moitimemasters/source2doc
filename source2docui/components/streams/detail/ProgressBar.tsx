interface ProgressBarProps {
    progress: number;
    label?: string;
}

export function ProgressBar({ progress, label }: ProgressBarProps) {
    return (
        <div className="space-y-2">
            {label && (
                <div className="flex justify-between text-sm">
                    <span className="text-muted-foreground">{label}</span>
                    <span className="font-semibold">{progress}%</span>
                </div>
            )}
            <div className="h-2 bg-secondary rounded-full overflow-hidden">
                <div
                    className="h-full bg-primary transition-all duration-300"
                    style={{ width: `${progress}%` }}
                />
            </div>
        </div>
    );
}
