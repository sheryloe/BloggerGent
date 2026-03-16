import * as React from "react";

import { cn } from "@/lib/utils";

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        "flex h-12 w-full rounded-2xl border border-slate-200/80 bg-white/85 px-4 py-2 text-sm text-slate-900 shadow-sm outline-none ring-offset-background placeholder:text-slate-400 focus-visible:ring-2 focus-visible:ring-indigo-400 dark:border-white/10 dark:bg-white/5 dark:text-zinc-100 dark:placeholder:text-zinc-500 dark:focus-visible:ring-indigo-400",
        className,
      )}
      {...props}
    />
  ),
);

Input.displayName = "Input";
