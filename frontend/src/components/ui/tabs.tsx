/* eslint-disable react-refresh/only-export-components -- Tabs is a
   direct re-export of Radix's Root primitive, not a function
   component declaration the Fast Refresh babel plugin can recognize.
   This only affects hot-reload DX, never runtime correctness, and is
   the standard shadcn/ui pattern for thin Radix wrappers. */
import * as React from "react";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import { cn } from "@/lib/utils";

export const Tabs = TabsPrimitive.Root;

export const TabsList = React.forwardRef<
  React.ComponentRef<typeof TabsPrimitive.List>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.List
    ref={ref}
    className={cn("flex gap-1 border-b border-ink-200", className)}
    {...props}
  />
));
TabsList.displayName = "TabsList";

export const TabsTrigger = React.forwardRef<
  React.ComponentRef<typeof TabsPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Trigger
    ref={ref}
    className={cn(
      "border-b-2 border-transparent px-4 py-2.5 text-sm font-medium text-ink-500 transition-colors",
      "hover:text-ink-900",
      "data-[state=active]:border-seal-500 data-[state=active]:text-ink-900",
      "focus-visible:outline-none",
      className
    )}
    {...props}
  />
));
TabsTrigger.displayName = "TabsTrigger";

export const TabsContent = React.forwardRef<
  React.ComponentRef<typeof TabsPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Content>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Content ref={ref} className={cn("pt-6 focus-visible:outline-none", className)} {...props} />
));
TabsContent.displayName = "TabsContent";
