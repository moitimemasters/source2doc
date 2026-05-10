import { StreamDetailContainer } from "@/components/streams/detail/StreamDetailContainer";

interface StreamDetailPageProps {
    params: Promise<{
        streamId: string;
    }>;
}

export default async function StreamDetailPage({ params }: StreamDetailPageProps) {
    const { streamId } = await params;
    return <StreamDetailContainer streamId={streamId} />;
}
