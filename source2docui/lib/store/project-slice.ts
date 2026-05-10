import { createSlice, createAsyncThunk, PayloadAction } from "@reduxjs/toolkit";
import { ProjectListItem } from "@/lib/wiki/project-types";

interface ProjectState {
    projects: ProjectListItem[];
    currentProjectId: string | null;
    loading: boolean;
    error: string | null;
}

const initialState: ProjectState = {
    projects: [],
    currentProjectId: null,
    loading: false,
    error: null,
};

export const fetchProjects = createAsyncThunk(
    "project/fetchProjects",
    async () => {
        const response = await fetch("/api/projects");
        if (!response.ok) {
            throw new Error("Failed to fetch projects");
        }
        const data = await response.json();
        return data;
    },
);

const projectSlice = createSlice({
    name: "project",
    initialState,
    reducers: {
        setCurrentProject: (state, action: PayloadAction<string>) => {
            state.currentProjectId = action.payload;
        },
        clearError: (state) => {
            state.error = null;
        },
    },
    extraReducers: (builder) => {
        builder
            .addCase(fetchProjects.pending, (state) => {
                state.loading = true;
                state.error = null;
            })
            .addCase(fetchProjects.fulfilled, (state, action) => {
                state.loading = false;
                state.projects = action.payload.projects || [];
                if (!state.currentProjectId && action.payload.defaultProject) {
                    state.currentProjectId = action.payload.defaultProject;
                }
            })
            .addCase(fetchProjects.rejected, (state, action) => {
                state.loading = false;
                state.error = action.error.message || "Failed to load projects";
            });
    },
});

export const { setCurrentProject, clearError } = projectSlice.actions;
export default projectSlice.reducer;
