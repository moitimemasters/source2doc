import { UseFormReturn } from "react-hook-form";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { GitBranch, Loader2 } from "lucide-react";
import { GitCloneFormData } from "@/lib/repos/schema";

interface GitCloneSectionProps {
    form: UseFormReturn<GitCloneFormData>;
    onSubmit: (data: GitCloneFormData) => void;
    isCloning: boolean;
}

export function GitCloneSection({
    form,
    onSubmit,
    isCloning,
}: GitCloneSectionProps) {
    const {
        register,
        formState: { errors },
        handleSubmit,
    } = form;

    return (
        <div className="space-y-4">
            <div className="space-y-2">
                <Label htmlFor="gitUrl">Git Repository URL *</Label>
                <Input
                    id="gitUrl"
                    type="url"
                    placeholder="https://github.com/user/repo.git"
                    {...register("gitUrl")}
                    disabled={isCloning}
                />
                {errors.gitUrl && (
                    <p className="text-sm text-destructive">
                        {errors.gitUrl.message}
                    </p>
                )}
            </div>

            <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2">
                    <Label htmlFor="branch">
                        Branch{" "}
                        <span className="text-muted-foreground font-normal">
                            (optional)
                        </span>
                    </Label>
                    <Input
                        id="branch"
                        placeholder="default branch"
                        {...register("branch")}
                        disabled={isCloning}
                    />
                    {errors.branch && (
                        <p className="text-sm text-destructive">
                            {errors.branch.message}
                        </p>
                    )}
                </div>

                <div className="space-y-2">
                    <Label htmlFor="commitSha">
                        Commit / Tag{" "}
                        <span className="text-muted-foreground font-normal">
                            (optional)
                        </span>
                    </Label>
                    <Input
                        id="commitSha"
                        placeholder="e.g. v1.2.0 or full SHA"
                        {...register("commitSha")}
                        disabled={isCloning}
                    />
                    {errors.commitSha && (
                        <p className="text-sm text-destructive">
                            {errors.commitSha.message}
                        </p>
                    )}
                    <p className="text-xs text-muted-foreground">
                        Worker checks out this ref after the clone — useful
                        for iterative-mode demos.
                    </p>
                </div>
            </div>

            <div className="space-y-2">
                <Label htmlFor="cloneName">
                    Repository Name{" "}
                    <span className="text-muted-foreground font-normal">
                        (optional, defaults to repo name from URL)
                    </span>
                </Label>
                <Input
                    id="cloneName"
                    placeholder="e.g., My Awesome Project"
                    {...register("name")}
                    disabled={isCloning}
                />
            </div>

            <div className="space-y-2">
                <Label htmlFor="cloneDescription">
                    Description{" "}
                    <span className="text-muted-foreground font-normal">
                        (optional)
                    </span>
                </Label>
                <Textarea
                    id="cloneDescription"
                    placeholder="Brief description of this repository"
                    rows={2}
                    {...register("description")}
                    disabled={isCloning}
                />
            </div>

            <div className="space-y-2">
                <Label htmlFor="cloneRepoId">
                    Repository ID{" "}
                    <span className="text-muted-foreground font-normal">
                        (optional UUID, gateway generates one if blank)
                    </span>
                </Label>
                <Input
                    id="cloneRepoId"
                    placeholder="e.g., 11111111-2222-4333-8444-555555555555"
                    {...register("repoId")}
                    disabled={isCloning}
                />
                {errors.repoId && (
                    <p className="text-sm text-destructive">
                        {errors.repoId.message}
                    </p>
                )}
            </div>

            <div className="flex items-start gap-2 rounded-lg border border-border p-3">
                <input
                    id="replaceExisting"
                    type="checkbox"
                    className="mt-1"
                    {...register("replaceExisting")}
                    disabled={isCloning}
                />
                <div className="text-sm">
                    <Label htmlFor="replaceExisting" className="cursor-pointer">
                        Replace existing repository
                    </Label>
                    <p className="text-xs text-muted-foreground mt-1">
                        Overwrite the tarball if a repo with this Repository
                        ID already exists. Use to refresh the same{" "}
                        <code className="font-mono">repo_id</code> to a newer
                        commit (so iterative-mode lineage stays intact).
                    </p>
                </div>
            </div>

            <Button
                type="button"
                className="w-full"
                disabled={isCloning}
                onClick={handleSubmit(onSubmit)}
            >
                {isCloning ? (
                    <>
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        Creating Clone Task...
                    </>
                ) : (
                    <>
                        <GitBranch className="mr-2 h-4 w-4" />
                        Clone Repository
                    </>
                )}
            </Button>
        </div>
    );
}
