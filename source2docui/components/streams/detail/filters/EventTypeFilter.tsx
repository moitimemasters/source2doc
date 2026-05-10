import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select";
import { Filter } from "lucide-react";

interface EventTypeFilterProps {
    value: string;
    onChange: (value: string) => void;
    eventTypes: string[];
}

export function EventTypeFilter({
    value,
    onChange,
    eventTypes,
}: EventTypeFilterProps) {
    return (
        <Select value={value} onValueChange={onChange}>
            <SelectTrigger className="w-full sm:w-[180px] h-9 text-sm font-mono">
                <Filter className="h-3.5 w-3.5 mr-1.5" />
                <SelectValue placeholder="Type" />
            </SelectTrigger>
            <SelectContent className="font-mono text-xs max-h-[300px]">
                <SelectItem value="all">All Types</SelectItem>
                {eventTypes.map((type) => (
                    <SelectItem key={type} value={type}>
                        {type}
                    </SelectItem>
                ))}
            </SelectContent>
        </Select>
    );
}
