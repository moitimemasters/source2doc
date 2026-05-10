import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select";
import { Filter } from "lucide-react";

interface PhaseFilterProps {
    value: string;
    onChange: (value: string) => void;
    phases: string[];
}

export function PhaseFilter({ value, onChange, phases }: PhaseFilterProps) {
    return (
        <Select value={value} onValueChange={onChange}>
            <SelectTrigger className="w-full sm:w-[140px] h-9 text-sm font-mono">
                <Filter className="h-3.5 w-3.5 mr-1.5" />
                <SelectValue placeholder="Phase" />
            </SelectTrigger>
            <SelectContent className="font-mono text-sm">
                <SelectItem value="all">All</SelectItem>
                {phases.map((phase) => (
                    <SelectItem key={phase} value={phase}>
                        {phase.charAt(0).toUpperCase() + phase.slice(1)}
                    </SelectItem>
                ))}
            </SelectContent>
        </Select>
    );
}
