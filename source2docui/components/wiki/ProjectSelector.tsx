import { useState } from "react";
import { Check, ChevronsUpDown, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
    Command,
    CommandEmpty,
    CommandGroup,
    CommandInput,
    CommandItem,
    CommandList,
} from "@/components/ui/command";
import {
    Popover,
    PopoverContent,
    PopoverTrigger,
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import { ProjectListItem } from "@/lib/wiki/project-types";

interface ProjectSelectorViewProps {
    projects: ProjectListItem[];
    currentProjectId: string | null;
    loading: boolean;
    onProjectChange: (projectId: string) => void;
}

export function ProjectSelectorView({
    projects,
    currentProjectId,
    loading,
    onProjectChange,
}: ProjectSelectorViewProps) {
    const [open, setOpen] = useState(false);

    const selectedProject = projects.find((p) => p.id === currentProjectId);

    const handleSelect = (projectId: string) => {
        setOpen(false);
        onProjectChange(projectId);
    };

    if (loading) {
        return (
            <Button variant="outline" disabled className="w-[200px]">
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Loading...
            </Button>
        );
    }

    if (projects.length <= 1) {
        return null;
    }

    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger asChild>
                <Button
                    variant="outline"
                    role="combobox"
                    aria-expanded={open}
                    className="w-[200px] justify-between"
                >
                    {selectedProject?.name || "Select project..."}
                    <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
                </Button>
            </PopoverTrigger>
            <PopoverContent className="w-[200px] p-0">
                <Command>
                    <CommandInput placeholder="Search projects..." />
                    <CommandList>
                        <CommandEmpty>No project found.</CommandEmpty>
                        <CommandGroup>
                            {projects.map((project) => (
                                <CommandItem
                                    key={project.id}
                                    value={project.id}
                                    onSelect={() => handleSelect(project.id)}
                                >
                                    <Check
                                        className={cn(
                                            "mr-2 h-4 w-4",
                                            currentProjectId === project.id
                                                ? "opacity-100"
                                                : "opacity-0",
                                        )}
                                    />
                                    <div className="flex flex-col">
                                        <span>{project.name}</span>
                                        {project.description && (
                                            <span className="text-xs text-muted-foreground">
                                                {project.description}
                                            </span>
                                        )}
                                    </div>
                                </CommandItem>
                            ))}
                        </CommandGroup>
                    </CommandList>
                </Command>
            </PopoverContent>
        </Popover>
    );
}
