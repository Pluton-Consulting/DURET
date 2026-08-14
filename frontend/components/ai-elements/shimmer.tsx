"use client";

import { cn } from "@/lib/utils";
import type { MotionProps } from "motion/react";
import { motion, useReducedMotion } from "motion/react";
import type { CSSProperties, ElementType, JSX } from "react";
import { memo, useMemo } from "react";

type MotionHTMLProps = MotionProps & Record<string, unknown>;

// Cache motion components at module level to avoid creating during render
const motionComponentCache = new Map<
  keyof JSX.IntrinsicElements,
  React.ComponentType<MotionHTMLProps>
>();

const getMotionComponent = (element: keyof JSX.IntrinsicElements) => {
  let component = motionComponentCache.get(element);
  if (!component) {
    component = motion.create(element);
    motionComponentCache.set(element, component);
  }
  return component;
};

export interface TextShimmerProps {
  children: string;
  as?: ElementType;
  className?: string;
  duration?: number;
  spread?: number;
}

const ShimmerComponent = ({
  children,
  as: Component = "p",
  className,
  duration = 2,
  spread = 2,
}: TextShimmerProps) => {
  const MotionComponent = getMotionComponent(
    Component as keyof JSX.IntrinsicElements
  );

  // LE MOUVEMENT SE COUPE QUAND L'UTILISATEUR L'A DEMANDÉ.
  //
  // Ce composant anime en JavaScript, pas en CSS : la règle
  // `prefers-reduced-motion` de la feuille globale — qui protège tout le
  // reste de l'application — n'a aucune prise sur lui. Sans cette garde, un
  // utilisateur sensible au mouvement verrait un texte défiler en boucle
  // sans fin pendant chaque attente, précisément ce qu'il a désactivé
  // partout ailleurs.
  //
  // On garde le dégradé (l'indice visuel « ça travaille ») mais on arrête
  // la boucle : le texte reste lisible, il ne bouge plus.
  const mouvementReduit = useReducedMotion();

  const dynamicSpread = useMemo(
    () => (children?.length ?? 0) * spread,
    [children, spread]
  );

  return (
    <MotionComponent
      animate={{ backgroundPosition: "0% center" }}
      className={cn(
        "relative inline-block bg-[length:250%_100%,auto] bg-clip-text text-transparent",
        "[--bg:linear-gradient(90deg,#0000_calc(50%-var(--spread)),var(--color-background),#0000_calc(50%+var(--spread)))] [background-repeat:no-repeat,padding-box]",
        className
      )}
      initial={{ backgroundPosition: "100% center" }}
      style={
        {
          "--spread": `${dynamicSpread}px`,
          backgroundImage:
            "var(--bg), linear-gradient(var(--color-muted-foreground), var(--color-muted-foreground))",
        } as CSSProperties
      }
      transition={
        mouvementReduit
          ? { duration: 0 }
          : {
              duration,
              ease: "linear",
              repeat: Number.POSITIVE_INFINITY,
            }
      }
    >
      {children}
    </MotionComponent>
  );
};

export const Shimmer = memo(ShimmerComponent);
