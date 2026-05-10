import { BundleExportFormContainer } from "@/components/bundles/BundleExportFormContainer";

export default function BundlesPage() {
    return (
        <div className="min-h-screen bg-gradient-to-b from-background to-muted/20">
            <div className="container mx-auto px-4 py-16">
                <div className="max-w-4xl mx-auto">
                    <BundleExportFormContainer />
                </div>
            </div>
        </div>
    );
}
