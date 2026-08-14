import * as React from "react"

import { cn } from "@/lib/utils"

/** `size` en MOT-CLÉ, pas en nombre.
 *
 *  L'attribut HTML natif `size` compte des caractères ; Extend UI l'emploie au
 *  sens de shadcn — un gabarit (`sm`, `lg`). Les deux ne peuvent pas cohabiter
 *  sous le même nom, alors on tranche pour le sens attendu par les composants
 *  qui nous appellent, et on ne transmet JAMAIS la valeur au DOM (React
 *  émettrait un avertissement, et le navigateur une largeur absurde).
 *
 *  Ici : le champ de numéro de page d'une visionneuse, où la hauteur par
 *  défaut déborde la barre d'outils. */
function Input({
  className,
  type,
  size,
  ...props
}: Omit<React.ComponentProps<"input">, "size"> & {
  size?: number | "default" | "sm" | "lg"
}) {
  // LES DEUX SENS COHABITENT. Un gabarit (`sm`) devient une classe et ne
  // descend PAS au DOM ; un nombre est l'attribut HTML natif et repart tel
  // quel. Sans cette distinction, `input-group` — qui relaie les props natives
  // — ne compilait plus.
  const gabaritDemande = typeof size === "string" ? size : "default"
  const tailleNative = typeof size === "number" ? size : undefined
  const gabarit = gabaritDemande === "sm" ? "h-8 px-2.5 text-sm"
    : gabaritDemande === "lg" ? "h-10 px-4"
    : "h-9 px-3"
  return (
    <input
      type={type}
      data-slot="input"
      data-size={gabaritDemande}
      size={tailleNative}
      className={cn(
        "w-full min-w-0 rounded-md border border-input bg-transparent py-1 text-base shadow-xs transition-[color,box-shadow] outline-none selection:bg-primary selection:text-primary-foreground file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground placeholder:text-muted-foreground disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 md:text-sm dark:bg-input/30",
        gabarit,
        "focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50",
        "aria-invalid:border-destructive aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40",
        className
      )}
      {...props}
    />
  )
}

export { Input }
