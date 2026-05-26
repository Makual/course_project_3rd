"use client";

import type * as React from "react";
import { cn } from "@/shared/lib/css";

type ModalProps = React.PropsWithChildren<{
  open: boolean;
  onOpenChange: (open: boolean) => void;
  className?: string;
}>;

export function Modal({ open, onOpenChange, className, children }: ModalProps) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50">
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={() => onOpenChange(false)}
      />
      <div
        className={cn(
          "absolute inset-4 md:inset-10 lg:inset-14 overflow-auto",
          className,
        )}
      >
        {children}
      </div>
    </div>
  );
}


