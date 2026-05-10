import { Input } from "@/components/ui/input";
import { Search } from "lucide-react";

interface SearchInputProps {
    value: string;
    onChange: (value: string) => void;
    placeholder?: string;
}

export function SearchInput({
    value,
    onChange,
    placeholder = "Search events...",
}: SearchInputProps) {
    return (
        <div className="relative flex-1">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <Input
                placeholder={placeholder}
                value={value}
                onChange={(e) => onChange(e.target.value)}
                className="pl-8 h-9 text-sm font-mono"
            />
        </div>
    );
}
