import * as React from "react";
import { cn } from "@/lib/dsai_utils";

const Card = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...dsai_props }, dsai_ref) => (
  <div
    ref={dsai_ref}
    className={cn(
      "rounded-lg border bg-card text-card-foreground shadow-sm",
      className
    )}
    {...dsai_props}
  />
));
Card.displayName = "Card";

const CardHeader = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...dsai_props }, dsai_ref) => (
  <div
    ref={dsai_ref}
    className={cn("flex flex-col space-y-1.5 p-6", className)}
    {...dsai_props}
  />
));
CardHeader.displayName = "CardHeader";

const CardTitle = React.forwardRef<
  HTMLParagraphElement,
  React.HTMLAttributes<HTMLHeadingElement>
>(({ className, ...dsai_props }, dsai_ref) => (
  <h3
    ref={dsai_ref}
    className={cn(
      "text-2xl font-semibold leading-none tracking-tight",
      className
    )}
    {...dsai_props}
  />
));
CardTitle.displayName = "CardTitle";

const CardDescription = React.forwardRef<
  HTMLParagraphElement,
  React.HTMLAttributes<HTMLParagraphElement>
>(({ className, ...dsai_props }, dsai_ref) => (
  <p
    ref={dsai_ref}
    className={cn("text-sm text-muted-foreground", className)}
    {...dsai_props}
  />
));
CardDescription.displayName = "CardDescription";

const CardContent = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...dsai_props }, dsai_ref) => (
  <div ref={dsai_ref} className={cn("p-6 pt-0", className)} {...dsai_props} />
));
CardContent.displayName = "CardContent";

const CardFooter = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...dsai_props }, dsai_ref) => (
  <div
    ref={dsai_ref}
    className={cn("flex items-center p-6 pt-0", className)}
    {...dsai_props}
  />
));
CardFooter.displayName = "CardFooter";

export {
  Card,
  CardHeader,
  CardFooter,
  CardTitle,
  CardDescription,
  CardContent,
};
