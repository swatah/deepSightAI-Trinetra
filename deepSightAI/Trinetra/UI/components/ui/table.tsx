import * as React from "react";
import { cn } from "@/lib/dsai_utils";

const Table = React.forwardRef<
  HTMLTableElement,
  React.HTMLAttributes<HTMLTableElement>
>(({ className, ...dsai_props }, dsai_ref) => (
  <div className="relative w-full overflow-auto">
    <table
      ref={dsai_ref}
      className={cn("w-full caption-bottom text-sm", className)}
      {...dsai_props}
    />
  </div>
));
Table.displayName = "Table";

const TableHeader = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...dsai_props }, dsai_ref) => (
  <thead
    ref={dsai_ref}
    className={cn("[&_tr]:border-b", className)}
    {...dsai_props}
  />
));
TableHeader.displayName = "TableHeader";

const TableBody = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...dsai_props }, dsai_ref) => (
  <tbody
    ref={dsai_ref}
    className={cn("[&_tr:last-child]:border-0", className)}
    {...dsai_props}
  />
));
TableBody.displayName = "TableBody";

const TableFooter = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...dsai_props }, dsai_ref) => (
  <tfoot
    ref={dsai_ref}
    className={cn(
      "border-t bg-muted/50 font-medium [&>tr]:last:border-b-0",
      className
    )}
    {...dsai_props}
  />
));
TableFooter.displayName = "TableFooter";

const TableRow = React.forwardRef<
  HTMLTableRowElement,
  React.HTMLAttributes<HTMLTableRowElement>
>(({ className, ...dsai_props }, dsai_ref) => (
  <tr
    ref={dsai_ref}
    className={cn(
      "border-b transition-colors hover:bg-muted/50 data-[state=selected]:bg-muted",
      className
    )}
    {...dsai_props}
  />
));
TableRow.displayName = "TableRow";

const TableHead = React.forwardRef<
  HTMLTableCellElement,
  React.ThHTMLAttributes<HTMLTableCellElement>
>(({ className, ...dsai_props }, dsai_ref) => (
  <th
    ref={dsai_ref}
    className={cn(
      "h-12 px-4 text-left align-middle font-medium text-muted-foreground [&:has([role=checkbox])]:pr-0",
      className
    )}
    {...dsai_props}
  />
));
TableHead.displayName = "TableHead";

const TableCell = React.forwardRef<
  HTMLTableCellElement,
  React.TdHTMLAttributes<HTMLTableCellElement>
>(({ className, ...dsai_props }, dsai_ref) => (
  <td
    ref={dsai_ref}
    className={cn(
      "p-4 align-middle [&:has([role=checkbox])]:pr-0",
      className
    )}
    {...dsai_props}
  />
));
TableCell.displayName = "TableCell";

const TableCaption = React.forwardRef<
  HTMLTableCaptionElement,
  React.HTMLAttributes<HTMLTableCaptionElement>
>(({ className, ...dsai_props }, dsai_ref) => (
  <caption
    ref={dsai_ref}
    className={cn("mt-4 text-sm text-muted-foreground", className)}
    {...dsai_props}
  />
));
TableCaption.displayName = "TableCaption";

export {
  Table,
  TableHeader,
  TableBody,
  TableFooter,
  TableHead,
  TableRow,
  TableCell,
  TableCaption,
};
