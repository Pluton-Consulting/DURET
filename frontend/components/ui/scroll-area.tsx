"use client"

import * as React from "react"
import { ScrollArea as ScrollAreaPrimitive } from "radix-ui"

import { cn } from "@/lib/utils"

/** L'ACCÈS AU VIEWPORT EST INDISPENSABLE À UNE VISIONNEUSE.
 *
 *  Extend UI doit piloter le défilement (aller à la page N, suivre la vignette
 *  active) et annoncer l'élément courant aux lecteurs d'écran. La version
 *  shadcn scelle le viewport : ni ref, ni classes, ni attributs. On l'ouvre —
 *  sans quoi la visionneuse ne peut pas faire son travail.
 *
 *  `scrollFade` ajoute un dégradé haut et bas, qui signale qu'il reste du
 *  contenu au-delà du bord. Sur une liste de vignettes coupée net, on croit
 *  être arrivé au bout.
 */
function ScrollArea({
  className,
  children,
  scrollFade = false,
  scrollbarGutter = false,
  orientation,
  viewportClassName,
  viewportProps,
  viewportRef,
  ...props
}: React.ComponentProps<typeof ScrollAreaPrimitive.Root> & {
  scrollFade?: boolean
  /** Réserve la gouttière de la barre : sans elle, le contenu se décale de
   *  quelques pixels à l'apparition de la barre, et un tableau tremble à
   *  chaque défilement. */
  scrollbarGutter?: boolean
  /** Extend UI l'annonce sur la zone ; Radix la porte sur la barre. */
  orientation?: "vertical" | "horizontal" | "both"
  viewportClassName?: string
  viewportProps?: React.ComponentProps<typeof ScrollAreaPrimitive.Viewport>
  viewportRef?: React.Ref<HTMLDivElement>
}) {
  const horizontale = orientation === "horizontal" || orientation === "both"
  const verticale = orientation !== "horizontal"
  return (
    <ScrollAreaPrimitive.Root
      data-slot="scroll-area"
      className={cn(
        "relative",
        scrollbarGutter && "[scrollbar-gutter:stable]",
        scrollFade &&
          "[mask-image:linear-gradient(to_bottom,transparent_0,black_12px,black_calc(100%-12px),transparent_100%)]",
        className
      )}
      {...props}
    >
      <ScrollAreaPrimitive.Viewport
        data-slot="scroll-area-viewport"
        ref={viewportRef}
        className={cn(
          "size-full rounded-[inherit] transition-[color,box-shadow] outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-1",
          viewportClassName
        )}
        {...viewportProps}
      >
        {children}
      </ScrollAreaPrimitive.Viewport>
      {verticale && <ScrollBar />}
      {horizontale && <ScrollBar orientation="horizontal" />}
      <ScrollAreaPrimitive.Corner />
    </ScrollAreaPrimitive.Root>
  )
}

function ScrollBar({
  className,
  orientation = "vertical",
  ...props
}: React.ComponentProps<typeof ScrollAreaPrimitive.ScrollAreaScrollbar>) {
  return (
    <ScrollAreaPrimitive.ScrollAreaScrollbar
      data-slot="scroll-area-scrollbar"
      orientation={orientation}
      className={cn(
        "flex touch-none p-px transition-colors select-none",
        orientation === "vertical" &&
          "h-full w-2.5 border-l border-l-transparent",
        orientation === "horizontal" &&
          "h-2.5 flex-col border-t border-t-transparent",
        className
      )}
      {...props}
    >
      <ScrollAreaPrimitive.ScrollAreaThumb
        data-slot="scroll-area-thumb"
        className="relative flex-1 rounded-full bg-border"
      />
    </ScrollAreaPrimitive.ScrollAreaScrollbar>
  )
}

export { ScrollArea, ScrollBar }
