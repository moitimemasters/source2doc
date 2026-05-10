import { AgentRunsPageContainer } from "@/components/agent-runs/AgentRunsPageContainer";

interface AgentRunsPageProps {
    params: Promise<{
        streamId: string;
    }>;
}

export default async function AgentRunsPage({ params }: AgentRunsPageProps) {
    const { streamId } = await params;
    return <AgentRunsPageContainer streamId={streamId} />;
}
