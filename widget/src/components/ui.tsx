/* Minimal shadcn/ui-style primitives (Card, Badge, Tabs) — same class
   conventions and tokens as shadcn, hand-rolled to keep the federated bundle
   free of radix. Swap for the real shadcn components if the widget grows. */

import { clsx, type ClassValue } from "clsx";
import { createContext, useContext, type ReactNode } from "react";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div
      className={cn(
        "rounded-xl border border-border bg-card text-card-foreground shadow-sm",
        className
      )}
    >
      {children}
    </div>
  );
}

export function CardHeader({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn("flex flex-col space-y-1 p-4 pb-2", className)}>{children}</div>;
}

export function CardTitle({ className, children }: { className?: string; children: ReactNode }) {
  return <h3 className={cn("text-base font-semibold leading-none tracking-tight m-0", className)}>{children}</h3>;
}

export function CardContent({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn("p-4 pt-2", className)}>{children}</div>;
}

const badgeVariants = {
  default: "bg-primary text-primary-foreground border-transparent",
  secondary: "bg-muted text-muted-foreground border-transparent",
  destructive: "bg-destructive text-white border-transparent",
  warning: "bg-warning text-white border-transparent",
  success: "bg-success text-white border-transparent",
  outline: "text-foreground border-border",
} as const;

export function Badge({
  variant = "default",
  className,
  children,
}: {
  variant?: keyof typeof badgeVariants;
  className?: string;
  children: ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium",
        badgeVariants[variant],
        className
      )}
    >
      {children}
    </span>
  );
}

/* ---- Tabs (state passed in; shadcn classes) ---- */

const TabsCtx = createContext<{ value: string; onChange: (v: string) => void }>({
  value: "",
  onChange: () => {},
});

export function Tabs({
  value,
  onValueChange,
  className,
  children,
}: {
  value: string;
  onValueChange: (v: string) => void;
  className?: string;
  children: ReactNode;
}) {
  return (
    <TabsCtx.Provider value={{ value, onChange: onValueChange }}>
      <div className={className}>{children}</div>
    </TabsCtx.Provider>
  );
}

export function TabsList({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div
      className={cn(
        "inline-flex h-8 items-center justify-center rounded-lg bg-muted p-1 text-muted-foreground",
        className
      )}
    >
      {children}
    </div>
  );
}

export function TabsTrigger({ value, children }: { value: string; children: ReactNode }) {
  const ctx = useContext(TabsCtx);
  const active = ctx.value === value;
  return (
    <button
      type="button"
      onClick={() => ctx.onChange(value)}
      className={cn(
        "inline-flex items-center justify-center whitespace-nowrap rounded-md px-2.5 py-0.5 text-xs font-medium transition-all cursor-pointer border-0",
        active
          ? "bg-background text-foreground shadow-sm"
          : "bg-transparent text-muted-foreground hover:text-foreground"
      )}
    >
      {children}
    </button>
  );
}

export function TabsContent({
  value,
  className,
  children,
}: {
  value: string;
  className?: string;
  children: ReactNode;
}) {
  const ctx = useContext(TabsCtx);
  if (ctx.value !== value) return null;
  return <div className={cn("mt-2", className)}>{children}</div>;
}
