import * as React from "react";

import { cn } from "@/lib/utils";

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...props }, ref) => (
    <textarea
      ref={ref}
      className={cn(
        "flex min-h-[120px] w-full rounded-3xl border border-ink/10 bg-white/80 px-4 py-3 text-sm text-ink shadow-sm outline-none placeholder:text-slate-400 focus-visible:ring-2 focus-visible:ring-ember",
        className
      )}
      {...props}
    />
  )
);

Textarea.displayName = "Textarea";
