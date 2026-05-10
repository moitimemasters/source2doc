"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
} from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { CheckCircle2, AlertCircle } from "lucide-react";
import { toast } from "sonner";
import {
    gitCloneSchema,
    defaultGitCloneValues,
    GitCloneFormData,
    fileUploadSchema,
    defaultFileUploadValues,
    FileUploadFormData,
} from "@/lib/repos/schema";
import { FileUploadSection } from "./FileUploadSection";
import { GitCloneSection } from "./GitCloneSection";

interface RepositoryUploadContainerProps {
    onSuccess?: (repoId: string, repoName: string) => void;
}

export function RepositoryUploadContainer({
    onSuccess,
}: RepositoryUploadContainerProps) {
    const [isUploading, setIsUploading] = useState(false);
    const [isCloning, setIsCloning] = useState(false);
    const [uploadedRepo, setUploadedRepo] = useState<{ id: string; name: string } | null>(null);
    const [clonedRepo, setClonedRepo] = useState<{ id: string; name: string } | null>(null);
    const [selectedFileName, setSelectedFileName] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);

    const cloneForm = useForm<GitCloneFormData>({
        resolver: zodResolver(gitCloneSchema),
        defaultValues: defaultGitCloneValues,
    });

    const uploadForm = useForm<FileUploadFormData>({
        resolver: zodResolver(fileUploadSchema),
        defaultValues: defaultFileUploadValues,
    });

    const handleFileSelect = (file: File) => {
        setSelectedFileName(file.name);
        // Auto-fill name from filename if empty
        const currentName = uploadForm.getValues("name");
        if (!currentName) {
            const nameFromFile = file.name
                .replace(/\.(tar\.gz|tgz)$/, "")
                .replace(/[-_]/g, " ")
                .replace(/\b\w/g, (c) => c.toUpperCase());
            uploadForm.setValue("name", nameFromFile);
        }
        uploadForm.handleSubmit((data) => handleFileUpload(file, data))();
    };

    const handleFileUpload = async (file: File, formData: FileUploadFormData) => {
        if (!file.name.endsWith(".tar.gz") && !file.name.endsWith(".tgz")) {
            toast.error("File must be a .tar.gz or .tgz archive");
            return;
        }

        setIsUploading(true);
        setError(null);
        setUploadedRepo(null);

        try {
            const fd = new FormData();
            fd.append("file", file);
            fd.append("name", formData.name);
            if (formData.description) {
                fd.append("description", formData.description);
            }

            const response = await fetch("/api/gateway/repos/upload", {
                method: "POST",
                body: fd,
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(
                    errorData.detail || "Failed to upload repository",
                );
            }

            const data = await response.json();
            const repoName = data.name || formData.name;
            setUploadedRepo({ id: data.repo_id, name: repoName });
            toast.success(`Repository "${repoName}" uploaded successfully!`);

            if (onSuccess) {
                onSuccess(data.repo_id, repoName);
            }
        } catch (err) {
            const errorMessage =
                err instanceof Error ? err.message : "Upload failed";
            setError(errorMessage);
            toast.error(errorMessage);
        } finally {
            setIsUploading(false);
            setSelectedFileName(null);
        }
    };

    const handleClone = async (data: GitCloneFormData) => {
        setIsCloning(true);
        setError(null);
        setClonedRepo(null);

        try {
            const response = await fetch("/api/gateway/repos/clone", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    git_url: data.gitUrl,
                    branch: data.branch?.trim() ? data.branch.trim() : undefined,
                    commit_sha: data.commitSha?.trim() || undefined,
                    name: data.name || undefined,
                    description: data.description || undefined,
                    repo_id: data.repoId?.trim() || undefined,
                    replace_existing: data.replaceExisting || undefined,
                }),
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(
                    errorData.detail || "Failed to clone repository",
                );
            }

            const result = await response.json();
            const repoName = result.name || data.name || data.gitUrl;
            setClonedRepo({ id: result.repo_id, name: repoName });
            toast.success(`Clone task created for "${repoName}"!`);

            if (onSuccess) {
                onSuccess(result.repo_id, repoName);
            }

            cloneForm.reset();
        } catch (err) {
            const errorMessage =
                err instanceof Error ? err.message : "Clone failed";
            setError(errorMessage);
            toast.error(errorMessage);
        } finally {
            setIsCloning(false);
        }
    };

    return (
        <Card>
            <CardHeader>
                <CardTitle>Upload Repository</CardTitle>
                <CardDescription>
                    Upload a repository archive or clone from Git
                </CardDescription>
            </CardHeader>
            <CardContent>
                {error && (
                    <Alert variant="destructive" className="mb-4">
                        <AlertCircle className="h-4 w-4" />
                        <AlertDescription>{error}</AlertDescription>
                    </Alert>
                )}

                <Tabs defaultValue="upload" className="w-full">
                    <TabsList className="grid w-full grid-cols-2">
                        <TabsTrigger value="upload">Upload Archive</TabsTrigger>
                        <TabsTrigger value="clone">Clone from Git</TabsTrigger>
                    </TabsList>

                    <TabsContent value="upload" className="space-y-4">
                        <FileUploadSection
                            form={uploadForm}
                            onFileSelect={handleFileSelect}
                            isUploading={isUploading}
                            selectedFileName={selectedFileName}
                        />

                        {uploadedRepo && (
                            <Alert className="border-green-500 bg-green-50 dark:bg-green-950">
                                <CheckCircle2 className="h-4 w-4 text-green-600" />
                                <AlertDescription className="text-green-600">
                                    <span className="font-medium">{uploadedRepo.name}</span> uploaded!{" "}
                                    ID:{" "}
                                    <code className="font-mono text-xs">
                                        {uploadedRepo.id}
                                    </code>
                                </AlertDescription>
                            </Alert>
                        )}
                    </TabsContent>

                    <TabsContent value="clone" className="space-y-4">
                        <GitCloneSection
                            form={cloneForm}
                            onSubmit={handleClone}
                            isCloning={isCloning}
                        />

                        {clonedRepo && (
                            <Alert className="border-green-500 bg-green-50 dark:bg-green-950">
                                <CheckCircle2 className="h-4 w-4 text-green-600" />
                                <AlertDescription className="text-green-600">
                                    Clone task created for{" "}
                                    <span className="font-medium">{clonedRepo.name}</span>!{" "}
                                    ID:{" "}
                                    <code className="font-mono text-xs">
                                        {clonedRepo.id}
                                    </code>
                                </AlertDescription>
                            </Alert>
                        )}
                    </TabsContent>
                </Tabs>
            </CardContent>
        </Card>
    );
}
