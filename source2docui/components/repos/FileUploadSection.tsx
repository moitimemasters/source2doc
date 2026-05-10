import { useRef } from "react";
import { UseFormReturn } from "react-hook-form";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Upload, Loader2 } from "lucide-react";
import { FileUploadFormData } from "@/lib/repos/schema";

interface FileUploadSectionProps {
    form: UseFormReturn<FileUploadFormData>;
    onFileSelect: (file: File) => void;
    isUploading: boolean;
    selectedFileName?: string | null;
}

export function FileUploadSection({
    form,
    onFileSelect,
    isUploading,
    selectedFileName,
}: FileUploadSectionProps) {
    const fileInputRef = useRef<HTMLInputElement>(null);
    const {
        register,
        formState: { errors },
    } = form;

    const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0];
        if (file) {
            onFileSelect(file);
        }
        if (fileInputRef.current) {
            fileInputRef.current.value = "";
        }
    };

    return (
        <div className="space-y-4">
            <div className="space-y-2">
                <Label htmlFor="uploadName">Repository Name *</Label>
                <Input
                    id="uploadName"
                    placeholder="e.g., My Awesome Project"
                    {...register("name")}
                    disabled={isUploading}
                />
                {errors.name && (
                    <p className="text-sm text-destructive">
                        {errors.name.message}
                    </p>
                )}
            </div>

            <div className="space-y-2">
                <Label htmlFor="uploadDescription">
                    Description{" "}
                    <span className="text-muted-foreground font-normal">
                        (optional)
                    </span>
                </Label>
                <Textarea
                    id="uploadDescription"
                    placeholder="Brief description of this repository"
                    rows={2}
                    {...register("description")}
                    disabled={isUploading}
                />
            </div>

            <div className="space-y-2">
                <Label htmlFor="file-upload">Archive file (.tar.gz or .tgz)</Label>
                <input
                    ref={fileInputRef}
                    id="file-upload"
                    type="file"
                    // ``accept=".tar.gz,.tgz"`` looks correct but browsers
                    // only match against the FINAL dot-extension — so a
                    // file named ``foo.tar.gz`` is filtered out (its
                    // extension is ``.gz``, not ``.tar.gz``). Listing
                    // ``.gz`` plus the gzip MIME types is the
                    // cross-browser way to make tar.gz files actually
                    // appear in the picker. The UI + server still
                    // validate the full ``.tar.gz`` / ``.tgz`` suffix
                    // before upload, so this just relaxes the picker
                    // filter, not the acceptance rule.
                    accept=".tar.gz,.tgz,.gz,application/gzip,application/x-gzip,application/x-gtar,application/x-compressed-tar"
                    onChange={handleFileChange}
                    disabled={isUploading}
                    className="hidden"
                />
                <Button
                    type="button"
                    variant="outline"
                    className="w-full"
                    onClick={() => fileInputRef.current?.click()}
                    disabled={isUploading}
                >
                    {isUploading ? (
                        <>
                            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                            Uploading...
                        </>
                    ) : (
                        <>
                            <Upload className="mr-2 h-4 w-4" />
                            {selectedFileName
                                ? selectedFileName
                                : "Choose File"}
                        </>
                    )}
                </Button>
                <p className="text-xs text-muted-foreground">
                    Select a .tar.gz or .tgz archive to upload
                </p>
            </div>
        </div>
    );
}
