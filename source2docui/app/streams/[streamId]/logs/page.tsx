import { LogsPageContainer } from "@/components/logs/LogsPageContainer";

interface LogsPageProps {
    params: Promise<{
        streamId: string;
    }>;
}

export default async function LogsPage({ params }: LogsPageProps) {
    const { streamId } = await params;
    return <LogsPageContainer streamId={streamId} />;
}
