/** Tailwind 4 passe par un greffon PostCSS dédié (plus de `tailwind.config.js`
 *  ni de directives `@tailwind` : la configuration vit dans `app/theme.css`,
 *  via `@theme`). */
const config = {
  plugins: {
    "@tailwindcss/postcss": {},
  },
}

export default config
