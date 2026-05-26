import type { ComponentPropsWithRef, PropsWithChildren } from "react";
import { cn } from "@/shared/lib/css";

type FlexProps = PropsWithChildren<ComponentPropsWithRef<"div">>;

export const Flex: React.FC<FlexProps> = ({
  children,
  className,
  ...props
}) => {
  return (
    <div className={cn("flex flex-row", className)} {...props}>
      {children}
    </div>
  );
};
