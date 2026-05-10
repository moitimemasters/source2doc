"use client";

import { useState } from "react";
import { toast } from "sonner";
import { useBundlesList } from "@/lib/bundles/use-bundles-list";
import { Button } from "@/components/ui/button";
import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
} from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Label } from "@/components/ui/label";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from "@/components/ui/table";
import { Download, Loader2, RefreshCw, Archive, AlertCircle } from "lucide-react";
import { useBundleExports } from "@/hooks/useBundleExports";

function formatBytes(bytes?: number) {
    if (bytes === undefined || bytes === null) return "";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let i = 0;
    let v = bytes;
    while (v >= 1024 && i < units.length - 1) {
        v /= 1024;
        i++;
    }
    const fixed = i === 0 ? 0 : 1;
    return `${v.toFixed(fixed)} ${units[i]}`;
}

export function BundleExportsSection() {
    const { bundles, error: bundlesError } = useBundlesList();
    const [bundleId, setBundleId] = useState<number | null>(null);

    const { exports, loading, error, refetch } = useBundleExports(bundleId);

    const handleDownload = async (s3Key: string) => {
        try {
            // Trigger browser download (server route sets Content-Disposition)
            window.location.href = `/api/gateway/bundles/exports/download?s3_key=${encodeURIComponent(
                s3Key,
            )}`;
        } catch {
            toast.error("Failed to start download");
        }
    };

    return (
        <Card>
            <CardHeader>
                <div className="flex items-center justify-between gap-4">
                    <div>
                        <CardTitle className="flex items-center gap-2">
                            <Archive className="h-5 w-5" />
                            Download exported bundles
                        </CardTitle>
                        <CardDescription>
                            List exported archives stored in S3 and download them (.tar.gz)
                        </CardDescription>
                    </div>
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={refetch}
                        disabled={loading || !bundleId}
                    >
                        <RefreshCw
                            className={`h-4 w-4 mr-2 ${loading ? "animate-spin" : ""}`}
                        />
                        Refresh
                    </Button>
                </div>
            </CardHeader>
            <CardContent className="space-y-4">
                <div className="space-y-2">
                    <Label htmlFor="bundleSelector">Bundle</Label>
                    <Select
                        value={bundleId ? String(bundleId) : ""}
                        onValueChange={(v) => setBundleId(Number(v) || null)}
                        disabled={!!bundlesError || bundles.length === 0}
                    >
                        <SelectTrigger id="bundleSelector">
                            <SelectValue
                                placeholder={
                                    bundlesError
                                        ? "Failed to load bundles"
                                        : bundles.length === 0
                                          ? "No bundles yet"
                                          : "Pick a bundle to list its exports"
                                }
                            />
                        </SelectTrigger>
                        <SelectContent>
                            {bundles.map((b) => (
                                <SelectItem key={b.id} value={String(b.id)}>
                                    <div className="flex flex-col">
                                        <span>
                                            {b.project_name ||
                                                b.name ||
                                                `Bundle #${b.id}`}
                                        </span>
                                        <span className="text-xs text-muted-foreground">
                                            {b.generation_id}
                                        </span>
                                    </div>
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </div>

                {bundlesError && (
                    <Alert variant="destructive">
                        <AlertCircle className="h-4 w-4" />
                        <AlertDescription>{bundlesError}</AlertDescription>
                    </Alert>
                )}

                {error && (
                    <Alert variant="destructive">
                        <AlertCircle className="h-4 w-4" />
                        <AlertDescription>{error}</AlertDescription>
                    </Alert>
                )}

                {!bundleId ? (
                    <div className="text-sm text-muted-foreground">
                        Pick a bundle above to see exported archives.
                    </div>
                ) : loading ? (
                    <div className="flex items-center justify-center py-8">
                        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                    </div>
                ) : exports.length === 0 ? (
                    <div className="text-sm text-muted-foreground">
                        No exports found in S3 for this bundle.
                    </div>
                ) : (
                    <div className="border rounded-lg overflow-hidden">
                        <Table>
                            <TableHeader>
                                <TableRow>
                                    <TableHead>Format</TableHead>
                                    <TableHead>S3 key</TableHead>
                                    <TableHead className="text-right">Size</TableHead>
                                    <TableHead className="text-right">Action</TableHead>
                                </TableRow>
                            </TableHeader>
                            <TableBody>
                                {exports.map((e) => (
                                    <TableRow key={e.s3_key}>
                                        <TableCell className="font-mono text-xs">
                                            {e.format}
                                        </TableCell>
                                        <TableCell className="font-mono text-xs truncate max-w-[380px]">
                                            {e.s3_key}
                                        </TableCell>
                                        <TableCell className="text-right text-xs text-muted-foreground">
                                            {formatBytes(e.size)}
                                        </TableCell>
                                        <TableCell className="text-right">
                                            <Button
                                                variant="secondary"
                                                size="sm"
                                                onClick={() =>
                                                    handleDownload(e.s3_key)
                                                }
                                            >
                                                <Download className="h-4 w-4 mr-2" />
                                                Download archive
                                            </Button>
                                        </TableCell>
                                    </TableRow>
                                ))}
                            </TableBody>
                        </Table>
                    </div>
                )}
            </CardContent>
        </Card>
    );
}
