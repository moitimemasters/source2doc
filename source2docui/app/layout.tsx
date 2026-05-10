import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { ThemeProvider } from "@/components/theme-provider";
import { StoreProvider } from "@/lib/store/StoreProvider";
import { Header } from "@/components/layout/Header";
import { Toaster } from "@/components/ui/sonner";
import "./globals.css";

export const metadata: Metadata = {
    title: {
        default: "Source2Doc",
        template: "%s · Source2Doc",
    },
    description:
        "Source2Doc — generate, browse, and tour LLM-authored documentation for your codebases.",
    icons: {
        icon: [
            {
                url: "/icon-light-32x32.png",
                media: "(prefers-color-scheme: light)",
            },
            {
                url: "/icon-dark-32x32.png",
                media: "(prefers-color-scheme: dark)",
            },
            {
                url: "/icon.svg",
                type: "image/svg+xml",
            },
        ],
        apple: "/apple-icon.png",
    },
};

export default function RootLayout({
    children,
}: Readonly<{
    children: React.ReactNode;
}>) {
    return (
        <html
            lang="en"
            suppressHydrationWarning
            className={`${GeistSans.variable} ${GeistMono.variable}`}
        >
            <body className="font-sans antialiased">
                <StoreProvider>
                    <ThemeProvider
                        attribute="class"
                        defaultTheme="system"
                        enableSystem
                    >
                        <Header />
                        {children}
                        <Toaster />
                    </ThemeProvider>
                </StoreProvider>
            </body>
        </html>
    );
}
