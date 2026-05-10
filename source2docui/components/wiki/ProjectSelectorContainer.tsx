"use client";

import { useEffect } from "react";
import { useRouter, usePathname } from "next/navigation";
import { useAppDispatch, useAppSelector } from "@/lib/store/hooks";
import { fetchProjects, setCurrentProject } from "@/lib/store/project-slice";
import { ProjectSelectorView } from "./ProjectSelector";

export function ProjectSelectorContainer() {
    const dispatch = useAppDispatch();
    const router = useRouter();
    const pathname = usePathname();
    const { projects, currentProjectId, loading } = useAppSelector(
        (state) => state.project,
    );

    useEffect(() => {
        dispatch(fetchProjects());
    }, [dispatch]);

    const handleProjectChange = (projectId: string) => {
        dispatch(setCurrentProject(projectId));

        if (pathname?.startsWith("/wiki/")) {
            router.push(`/wiki/${projectId}`);
        }
    };

    return (
        <ProjectSelectorView
            projects={projects}
            currentProjectId={currentProjectId}
            loading={loading}
            onProjectChange={handleProjectChange}
        />
    );
}
