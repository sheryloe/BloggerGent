import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center rounded-full text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 focus-visible:ring-offset-2 focus-visible:ring-offset-white disabled:pointer-events-none disabled:opacity-50 dark:focus-visible:ring-offset-zinc-950",
  {
    variants: {
      variant: {
        default:
          "bg-indigo-600 text-white shadow-[0_12px_30px_rgba(79,70,229,0.28)] hover:bg-indigo-500 dark:bg-indigo-500 dark:hover:bg-indigo-400",
        outline:
          "border border-slate-200/80 bg-white/80 text-slate-900 hover:bg-slate-100 dark:border-white/10 dark:bg-white/5 dark:text-zinc-100 dark:hover:bg-white/10",
        ghost:
          "text-slate-700 hover:bg-slate-100 dark:text-zinc-200 dark:hover:bg-white/10",
        accent:
          "bg-emerald-500 text-white shadow-[0_12px_30px_rgba(16,185,129,0.24)] hover:bg-emerald-400 dark:bg-emerald-500 dark:hover:bg-emerald-400",
      },
      size: {
        default: "h-12 px-5",
        sm: "h-9 px-4 text-xs",
        lg: "h-12 px-6 text-sm sm:h-14",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />;
  },
);
Button.displayName = "Button";

export { Button, buttonVariants };
