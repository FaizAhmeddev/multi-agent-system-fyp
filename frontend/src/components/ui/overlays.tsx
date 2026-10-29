import * as RD from "@radix-ui/react-dialog";
import * as RM from "@radix-ui/react-dropdown-menu";
import * as RT from "@radix-ui/react-tabs";
import type { ReactNode } from "react";
import { X } from "../icons";
import { cx } from "./primitives";

export function Dialog({
  open, onOpenChange, title, description, children, footer, wide,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  title: string;
  description?: string;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}) {
  return (
    <RD.Root open={open} onOpenChange={onOpenChange}>
      <RD.Portal>
        <RD.Overlay className="fixed inset-0 z-40 bg-black/50" />
        <RD.Content
          className={cx(
            "fixed left-1/2 top-1/2 z-50 flex max-h-[90vh] w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2 flex-col",
            "rounded-lg border border-border bg-surface shadow-[var(--shadow)] focus:outline-none",
            wide ? "max-w-3xl" : "max-w-lg",
          )}
        >
          <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
            <div>
              <RD.Title className="text-base font-semibold">{title}</RD.Title>
              {description ? (
                <RD.Description className="mt-1 text-sm text-muted">{description}</RD.Description>
              ) : (
                <RD.Description className="sr-only">{title}</RD.Description>
              )}
            </div>
            <RD.Close aria-label="Close" className="rounded-md p-1 text-muted hover:bg-surface-2 hover:text-fg">
              <X aria-hidden className="size-4" />
            </RD.Close>
          </div>
          <div className="overflow-y-auto px-5 py-4">{children}</div>
          {footer && <div className="flex justify-end gap-2 border-t border-border px-5 py-3">{footer}</div>}
        </RD.Content>
      </RD.Portal>
    </RD.Root>
  );
}

export interface MenuItem {
  label: string;
  onSelect: () => void;
  icon?: ReactNode;
  danger?: boolean;
  disabled?: boolean;
}

export function Menu({ trigger, items, label }: { trigger: ReactNode; items: (MenuItem | "separator")[]; label?: string }) {
  return (
    <RM.Root>
      <RM.Trigger asChild>{trigger}</RM.Trigger>
      <RM.Portal>
        <RM.Content
          align="end"
          sideOffset={6}
          aria-label={label}
          className="z-50 min-w-44 rounded-md border border-border bg-surface p-1 text-sm shadow-[var(--shadow)]"
        >
          {items.map((it, i) =>
            it === "separator" ? (
              <RM.Separator key={`s${i}`} className="my-1 h-px bg-border" />
            ) : (
              <RM.Item
                key={it.label}
                disabled={it.disabled}
                onSelect={it.onSelect}
                className={cx(
                  "flex cursor-pointer select-none items-center gap-2 rounded px-2 py-1.5 outline-none",
                  "data-[highlighted]:bg-surface-2 data-[disabled]:cursor-not-allowed data-[disabled]:opacity-50",
                  it.danger && "text-danger",
                )}
              >
                {it.icon}
                {it.label}
              </RM.Item>
            ),
          )}
        </RM.Content>
      </RM.Portal>
    </RM.Root>
  );
}

export function Tabs({
  value, onValueChange, tabs, children, label,
}: {
  value: string;
  onValueChange: (v: string) => void;
  tabs: { value: string; label: ReactNode }[];
  children: ReactNode;
  label: string;
}) {
  return (
    <RT.Root value={value} onValueChange={onValueChange}>
      <RT.List aria-label={label} className="mb-4 flex gap-1 overflow-x-auto border-b border-border">
        {tabs.map((t) => (
          <RT.Trigger
            key={t.value}
            value={t.value}
            className={cx(
              "-mb-px whitespace-nowrap border-b-2 border-transparent px-3 py-2 text-sm font-medium text-muted",
              "hover:text-fg data-[state=active]:border-primary data-[state=active]:text-fg",
            )}
          >
            {t.label}
          </RT.Trigger>
        ))}
      </RT.List>
      {children}
    </RT.Root>
  );
}

export const TabPanel = RT.Content;
